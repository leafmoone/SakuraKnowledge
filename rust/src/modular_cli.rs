//! Argument-only validation for the modular CLI, before discovery or asset access.

use std::fmt;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ParsedCommand {
    pub command: String,
    /// Legacy `related` keeps KIND, NAMESPACE, VALUE in their original order.
    pub positionals: Vec<String>,
    /// Flattened, nonempty pack IDs, deduplicated in first-seen order.
    pub sources: Vec<String>,
    pub kind: Option<String>,
    pub namespace: Option<String>,
    pub relation: Option<String>,
    pub filter: Option<String>,
    pub target_namespace: Option<String>,
    pub direction: String,
    pub limit: u32,
    pub key: bool,
    pub category: Option<i64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UsageError(pub String);

impl fmt::Display for UsageError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for UsageError {}

const COMMANDS: &[&str] = &[
    "packs",
    "inspect",
    "lookup",
    "search",
    "related",
    "ask",
    "resolve-tag",
    "retrieve",
];

fn allowed(command: &str, option: &str) -> bool {
    match option {
        "--source" => command != "packs",
        "--kind" | "--namespace" => !matches!(command, "packs" | "inspect"),
        "--key" => matches!(command, "lookup" | "resolve-tag"),
        "--limit" => matches!(command, "search" | "related" | "resolve-tag" | "retrieve"),
        "--topk" => matches!(command, "search" | "retrieve"),
        "--relation" | "--filter" | "--direction" => command == "related",
        "--target-namespace" | "--target-tag-namespace" => {
            matches!(command, "ask" | "resolve-tag")
        }
        "--category" => command == "resolve-tag",
        _ => false,
    }
}

fn set_option<T: PartialEq>(
    slot: &mut Option<T>,
    value: T,
    option: &str,
) -> Result<(), UsageError> {
    if slot.as_ref().is_some_and(|previous| *previous != value) {
        return Err(UsageError(format!("argument {option}: conflicting values")));
    }
    *slot = Some(value);
    Ok(())
}

fn add_sources(sources: &mut Vec<String>, value: &str) -> Result<(), UsageError> {
    for source in value.split(',') {
        // Match the manifest pack-ID boundary, not a filesystem path.
        if source.is_empty()
            || source.len() > 128
            || matches!(source, "." | "..")
            || !source
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"-_.".contains(&b))
        {
            return Err(UsageError(format!(
                "argument --source: invalid source pack ID '{source}'"
            )));
        }
        if !sources.iter().any(|existing| existing == source) {
            sources.push(source.to_owned());
        }
    }
    Ok(())
}

/// Parse arguments after COMMAND, without opening config, packs, or model assets.
///
/// Options may precede or follow positionals. Single-dash strings are ordinary
/// values; `--` ends option parsing so a positional can also start with `--`.
/// Value-taking options require a separate, nonempty token, never another option.
/// Identity and filter values are preserved verbatim, without business validation.
pub fn parse(command: &str, args: &[String]) -> Result<ParsedCommand, UsageError> {
    if !COMMANDS.contains(&command) {
        return Err(UsageError(format!(
            "argument command: invalid choice: '{command}' (choose from {})",
            COMMANDS.join(", ")
        )));
    }
    let mut parsed = ParsedCommand {
        command: command.to_owned(),
        positionals: Vec::new(),
        sources: Vec::new(),
        kind: None,
        namespace: None,
        relation: None,
        filter: None,
        target_namespace: None,
        direction: "out".to_owned(),
        limit: 10,
        key: false,
        category: None,
    };
    let mut limit = None;
    let mut direction = None;
    let mut options = true;
    let mut i = 0;
    while i < args.len() {
        let token = args[i].as_str();
        i += 1;
        if options && token == "--" {
            options = false;
            continue;
        }
        if !options || !token.starts_with("--") {
            parsed.positionals.push(token.to_owned());
            continue;
        }
        if !allowed(command, token) {
            return Err(UsageError(format!(
                "unrecognized arguments for {command}: {token}"
            )));
        }
        if token == "--key" {
            parsed.key = true;
            continue;
        }
        let value = args
            .get(i)
            .filter(|value| !value.starts_with("--"))
            .ok_or_else(|| UsageError(format!("argument {token}: expected a value")))?;
        i += 1;
        if value.is_empty() {
            return Err(UsageError(format!(
                "argument {token}: expected a nonempty value"
            )));
        }
        match token {
            "--source" => add_sources(&mut parsed.sources, value)?,
            "--kind" => set_option(&mut parsed.kind, value.clone(), token)?,
            "--namespace" => set_option(&mut parsed.namespace, value.clone(), token)?,
            "--relation" => set_option(&mut parsed.relation, value.clone(), token)?,
            "--filter" => set_option(&mut parsed.filter, value.clone(), token)?,
            "--target-namespace" | "--target-tag-namespace" => {
                set_option(&mut parsed.target_namespace, value.clone(), token)?;
            }
            "--limit" | "--topk" => {
                let number = value
                    .parse::<u32>()
                    .ok()
                    .filter(|number| (1..=100).contains(number))
                    .ok_or_else(|| {
                        UsageError(format!("argument {token}: expected an integer in 1..100"))
                    })?;
                set_option(&mut limit, number, token)?;
            }
            "--category" => {
                let number = value.parse::<i64>().map_err(|_| {
                    UsageError(format!("argument {token}: expected an integer in i64 range"))
                })?;
                set_option(&mut parsed.category, number, token)?;
            }
            "--direction" => {
                if !matches!(value.as_str(), "out" | "in") {
                    return Err(UsageError("argument --direction: expected out or in".into()));
                }
                set_option(&mut direction, value.clone(), token)?;
            }
            _ => unreachable!("allowed options are handled above"),
        }
    }
    parsed.limit = limit.unwrap_or(10);
    parsed.direction = direction.unwrap_or_else(|| "out".to_owned());

    let count = parsed.positionals.len();
    let valid_arity = match command {
        "packs" | "inspect" => count == 0,
        "related" => count == 1 || count == 3,
        _ => count == 1,
    };
    if !valid_arity {
        let required = match command {
            "packs" | "inspect" => "no positional arguments",
            "related" => "VALUE with --kind and --namespace, or KIND NAMESPACE VALUE",
            _ => "exactly one QUERY positional argument",
        };
        return Err(UsageError(format!("{command} requires {required}")));
    }
    if parsed.positionals.iter().any(String::is_empty) {
        return Err(UsageError(format!(
            "{command} positional arguments must not be empty"
        )));
    }
    if (parsed.key || (command == "related" && count == 1))
        && (parsed.kind.is_none() || parsed.namespace.is_none())
    {
        return Err(UsageError(
            "exact key requires --kind and --namespace".into(),
        ));
    }
    if command == "related" && count == 3 {
        if parsed.namespace.is_some() {
            return Err(UsageError(
                "argument --namespace: only applicable to related VALUE form".into(),
            ));
        }
        // In the legacy form --kind is a destination filter, not the source key.
        if let (Some(kind), Some(filter)) = (&parsed.kind, &parsed.filter) {
            if kind != filter {
                return Err(UsageError(
                    "arguments --kind and --filter: conflicting destination filters".into(),
                ));
            }
        }
    }
    Ok(parsed)
}
