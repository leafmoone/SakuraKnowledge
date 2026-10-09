//! One absolute monotonic request deadline, excluding cold open and input waiting.
//! Native callers reuse one watchdog; expiry kills only this process, without I/O.
use std::error::Error;
use std::io;
use std::sync::{Arc, Condvar, Mutex};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

pub const REQUEST_BUDGET: Duration = Duration::from_secs(5);
pub const DEADLINE_EXIT_CODE: i32 = 124;

/// Fatal: this is deliberately not a recoverable resident RequestError.
#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub struct DeadlineExceeded;

impl std::fmt::Display for DeadlineExceeded {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str("request_deadline_exceeded")
    }
}
impl Error for DeadlineExceeded {}

#[derive(Debug, Clone, Copy)]
pub struct RequestDeadline {
    started: Instant,
    expires: Instant,
}

impl RequestDeadline {
    /// Call immediately after a complete input line, or after single-query cold open.
    pub fn start() -> Self { Self::from_start(Instant::now(), REQUEST_BUDGET) }

    pub fn from_start(started: Instant, budget: Duration) -> Self {
        Self { started, expires: started + budget }
    }

    pub fn expires_at(self) -> Instant { self.expires }
    pub fn elapsed(self) -> Duration { self.started.elapsed() }

    /// Remaining engine time, never a fresh per-stage budget.
    pub fn remaining(self) -> Result<Duration, DeadlineExceeded> {
        self.expires.checked_duration_since(Instant::now())
            .filter(|remaining| !remaining.is_zero()).ok_or(DeadlineExceeded)
    }

    pub fn check(self) -> Result<(), DeadlineExceeded> {
        self.remaining().map(|_| ())
    }

    /// Generic/mock callers get checks, not a thread that exits their host process.
    pub fn guard(self) -> DeadlineGuard {
        DeadlineGuard { deadline: self, registration: None }
    }
}

#[derive(Clone, Copy)]
struct Armed {
    generation: u64,
    deadline: RequestDeadline,
}

#[derive(Default)]
struct State {
    generation: u64,
    active: Option<Armed>,
    expired: bool,
    stopping: bool,
}

struct Shared {
    state: Mutex<State>,
    changed: Condvar,
    expire: Box<dyn Fn() + Send + Sync>,
}

impl Shared {
    /// Claim expiry under the same mutex as disarming, so the callback runs once.
    fn expire_locked(state: &mut State) -> bool {
        if state.expired { return false; }
        state.expired = true;
        state.active = None;
        true
    }

    fn release(&self, generation: u64, deadline: RequestDeadline) -> Result<(), DeadlineExceeded> {
        let mut state = self.state.lock().unwrap();
        let late = state.expired || deadline.check().is_err();
        let same = state.active.is_some_and(|active| active.generation == generation);
        let fire = if same && late {
            Self::expire_locked(&mut state)
        } else {
            if same { state.active = None; }
            false
        };
        self.changed.notify_one();
        drop(state);
        if fire { (self.expire)(); }
        if late { Err(DeadlineExceeded) } else { Ok(()) }
    }
}

/// A controller owns exactly one sleeping thread, not one thread per request.
/// Keep it alive across requests. Native expiry never tries to emit a FAIL frame
/// or log on stderr: either pipe can be blocked. Clients must reject incomplete
/// frames after a nonzero exit. Scheduling latency is not a real-time guarantee.
pub struct DeadlineWatchdog {
    shared: Arc<Shared>,
    worker: Option<JoinHandle<()>>,
}

impl DeadlineWatchdog {
    /// Thread startup failure must be returned before emitting the opened event.
    pub fn start() -> io::Result<Self> {
        Self::with_expiry_action(|| terminate_current_process())
    }

    fn with_expiry_action(expire: impl Fn() + Send + Sync + 'static) -> io::Result<Self> {
        let shared = Arc::new(Shared {
            state: Mutex::new(State::default()),
            changed: Condvar::new(),
            expire: Box::new(expire),
        });
        let timer = Arc::clone(&shared);
        let worker = thread::Builder::new().name("request-deadline".into()).spawn(move || {
            let mut state = timer.state.lock().unwrap();
            loop {
                if state.stopping || state.expired { return; }
                let Some(active) = state.active else {
                    state = timer.changed.wait(state).unwrap();
                    continue;
                };
                match active.deadline.remaining() {
                    Ok(remaining) => {
                        // Always re-read generation/deadline after wakeup, including
                        // spurious wakes and a previous request's timed-out wait.
                        state = timer.changed.wait_timeout(state, remaining).unwrap().0;
                    }
                    Err(_) => {
                        let fire = Shared::expire_locked(&mut state);
                        drop(state);
                        if fire { (timer.expire)(); }
                        return;
                    }
                }
            }
        })?;
        Ok(Self { shared, worker: Some(worker) })
    }

    pub fn arm(&self, deadline: RequestDeadline) -> Result<DeadlineGuard, DeadlineExceeded> {
        let mut state = self.shared.state.lock().unwrap();
        if state.expired || state.stopping { return Err(DeadlineExceeded); }
        assert!(state.active.is_none(), "only one native request may be active");
        state.generation = state.generation.checked_add(1).expect("deadline generation overflow");
        let generation = state.generation;
        state.active = Some(Armed { generation, deadline });
        self.shared.changed.notify_one();
        drop(state);
        let guard = DeadlineGuard {
            deadline,
            registration: Some((Arc::clone(&self.shared), generation)),
        };
        deadline.check()?;
        Ok(guard)
    }
}

impl Drop for DeadlineWatchdog {
    fn drop(&mut self) {
        let mut state = self.shared.state.lock().unwrap();
        let fire = if state.active.is_some_and(|active| active.deadline.check().is_err()) {
            Shared::expire_locked(&mut state)
        } else { false };
        state.stopping = true;
        state.active = None;
        self.shared.changed.notify_one();
        drop(state);
        if fire { (self.shared.expire)(); }
        if let Some(worker) = self.worker.take() {
            // Join on shutdown rather than leak one controller thread per invocation.
            let _ = worker.join();
        }
    }
}

pub struct DeadlineGuard {
    deadline: RequestDeadline,
    registration: Option<(Arc<Shared>, u64)>,
}

impl DeadlineGuard {
    pub fn deadline(&self) -> RequestDeadline { self.deadline }
    pub fn check(&self) -> Result<(), DeadlineExceeded> { self.deadline.check() }

    /// Disarm only after response write/flush and a final absolute-time check.
    pub fn finish(mut self) -> Result<(), DeadlineExceeded> {
        match self.registration.take() {
            Some((shared, generation)) => shared.release(generation, self.deadline),
            None => self.deadline.check(),
        }
    }
}

impl Drop for DeadlineGuard {
    fn drop(&mut self) {
        if let Some((shared, generation)) = self.registration.take() {
            // An expired guard must not cancel its fatal timeout during unwinding.
            let _ = shared.release(generation, self.deadline);
        }
    }
}

/// No Rust/C stdio flushing, destructors, other PID, or external dependency.
#[cfg(windows)]
pub fn terminate_current_process() -> ! {
    #[link(name = "kernel32")]
    extern "system" {
        fn GetCurrentProcess() -> *mut std::ffi::c_void;
        fn TerminateProcess(process: *mut std::ffi::c_void, code: u32) -> i32;
    }
    // SAFETY: GetCurrentProcess returns a pseudo-handle to this process only.
    // TerminateProcess does not run cleanup or wait on the blocked stdout lock.
    unsafe { TerminateProcess(GetCurrentProcess(), DEADLINE_EXIT_CODE as u32); }
    std::process::abort() // Defensive fallback only if the OS rejects termination.
}

#[cfg(unix)]
pub fn terminate_current_process() -> ! {
    extern "C" { fn _exit(code: i32) -> !; }
    // SAFETY: _exit terminates only the calling process without stdio cleanup.
    unsafe { _exit(DEADLINE_EXIT_CODE) }
}

#[cfg(not(any(windows, unix)))]
pub fn terminate_current_process() -> ! { std::process::exit(DEADLINE_EXIT_CODE) }

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::mpsc;
    use std::sync::atomic::{AtomicUsize, Ordering};

    #[test]
    fn deadline_is_absolute_and_expiry_is_an_explicit_error() {
        let deadline = RequestDeadline::from_start(Instant::now() - Duration::from_secs(1), Duration::from_millis(20));
        assert_eq!(deadline.check(), Err(DeadlineExceeded));
        assert_eq!(deadline.remaining(), Err(DeadlineExceeded));
        assert_eq!(deadline.guard().finish(), Err(DeadlineExceeded));
    }

    #[test]
    fn expiry_callback_runs_once_without_exiting_the_test_process() {
        let calls = Arc::new(AtomicUsize::new(0));
        let observed = Arc::clone(&calls);
        let (sent, received) = mpsc::channel();
        let watchdog = DeadlineWatchdog::with_expiry_action(move || {
            observed.fetch_add(1, Ordering::SeqCst);
            sent.send(()).unwrap();
        }).unwrap();
        let guard = watchdog.arm(RequestDeadline::from_start(Instant::now(), Duration::from_millis(20))).unwrap();
        received.recv_timeout(Duration::from_secs(2)).unwrap();
        assert_eq!(guard.finish(), Err(DeadlineExceeded));
        assert!(watchdog.arm(RequestDeadline::start()).is_err());
        drop(watchdog);
        assert_eq!(calls.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn old_generation_cannot_disarm_or_expire_the_next_request() {
        let calls = Arc::new(AtomicUsize::new(0));
        let observed = Arc::clone(&calls);
        let watchdog = DeadlineWatchdog::with_expiry_action(move || {
            observed.fetch_add(1, Ordering::SeqCst);
        }).unwrap();
        let first = watchdog.arm(RequestDeadline::from_start(Instant::now(), Duration::from_millis(20))).unwrap();
        let (shared, generation) = first.registration.as_ref().unwrap();
        let shared = Arc::clone(shared);
        let generation = *generation;
        let old_deadline = first.deadline();
        first.finish().unwrap();
        let second = watchdog.arm(RequestDeadline::start()).unwrap();
        thread::sleep(Duration::from_millis(40));
        // Simulate a delayed release of an old guard after its old deadline.
        assert_eq!(shared.release(generation, old_deadline), Err(DeadlineExceeded));
        assert!(shared.state.lock().unwrap().active.is_some());
        second.finish().unwrap();
        drop(watchdog);
        assert_eq!(calls.load(Ordering::SeqCst), 0);
    }

    #[test]
    fn dropping_an_expired_guard_does_not_cancel_expiry() {
        let calls = Arc::new(AtomicUsize::new(0));
        let observed = Arc::clone(&calls);
        let watchdog = DeadlineWatchdog::with_expiry_action(move || {
            observed.fetch_add(1, Ordering::SeqCst);
        }).unwrap();
        let guard = watchdog.arm(RequestDeadline::start()).unwrap();
        // Deterministically make both the guard and controller overdue without
        // depending on which thread gets scheduled first.
        let expired = RequestDeadline::from_start(Instant::now() - Duration::from_secs(1), Duration::ZERO);
        let mut guard = guard;
        guard.deadline = expired;
        watchdog.shared.state.lock().unwrap().active.as_mut().unwrap().deadline = expired;
        drop(guard);
        drop(watchdog);
        assert_eq!(calls.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn dropped_unexpired_guard_and_idle_controller_do_not_fire() {
        let calls = Arc::new(AtomicUsize::new(0));
        let observed = Arc::clone(&calls);
        let watchdog = DeadlineWatchdog::with_expiry_action(move || {
            observed.fetch_add(1, Ordering::SeqCst);
        }).unwrap();
        drop(watchdog.arm(RequestDeadline::start()).unwrap());
        watchdog.arm(RequestDeadline::start()).unwrap().finish().unwrap();
        drop(watchdog);
        assert_eq!(calls.load(Ordering::SeqCst), 0);
    }
}
