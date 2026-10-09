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

#[cfg(test)]
mod tests {
    use super::*;

    const OPTIONS: &[(&str, Option<&str>)] = &[
        ("--source", Some("future.pack")),
        ("--kind", Some("character")),
        ("--namespace", Some("custom")),
        ("--key", None),
        ("--limit", Some("5")),
        ("--topk", Some("5")),
        ("--relation", Some("member_of")),
        ("--filter", Some("tag")),
        ("--direction", Some("in")),
        ("--target-namespace", Some("custom:tag")),
        ("--target-tag-namespace", Some("custom:tag")),
        ("--category", Some("-1")),
    ];

    fn strings(values: &[&str]) -> Vec<String> {
        values.iter().map(|value| (*value).to_owned()).collect()
    }

    fn base(command: &str) -> Vec<String> {
        match command {
            "packs" | "inspect" => Vec::new(),
            "related" => strings(&["value", "--kind", "character", "--namespace", "custom"]),
            _ => strings(&["query", "--kind", "character", "--namespace", "custom"]),
        }
    }

    fn run(command: &str, values: &[&str]) -> Result<ParsedCommand, UsageError> {
        parse(command, &strings(values))
    }

    #[test]
    fn defaults_for_every_command() {
        for &command in COMMANDS {
            let parsed = parse(command, &base(command)).unwrap();
            assert_eq!(parsed.command, command);
            assert_eq!(parsed.limit, 10);
            assert_eq!(parsed.direction, "out");
            assert!(!parsed.key);
            assert!(parsed.sources.is_empty());
            assert!(parsed.category.is_none());
            assert!(parsed.target_namespace.is_none());
        }
        for command in ["lookup", "search", "ask", "resolve-tag", "retrieve"] {
            let parsed = run(command, &["q"]).unwrap();
            assert!(parsed.kind.is_none());
            assert!(parsed.namespace.is_none());
        }
    }

    #[test]
    fn unknown_commands_are_usage_errors() {
        for command in ["", "runtime", "lookpu", "LOOKUP", "--help"] {
            assert!(run(command, &[]).is_err(), "accepted {command}");
        }
    }

    #[test]
    fn command_option_allowlists() {
        for &command in COMMANDS {
            let expected: &[&str] = match command {
                "packs" => &[],
                "inspect" => &["--source"],
                "lookup" => &["--kind", "--namespace", "--key", "--source"],
                "search" | "retrieve" => {
                    &["--kind", "--namespace", "--limit", "--topk", "--source"]
                }
                "related" => &[
                    "--kind", "--namespace", "--relation", "--filter", "--limit",
                    "--direction", "--source",
                ],
                "ask" => &[
                    "--kind", "--namespace", "--target-namespace",
                    "--target-tag-namespace", "--source",
                ],
                "resolve-tag" => &[
                    "--kind", "--namespace", "--key", "--limit", "--category",
                    "--target-namespace", "--target-tag-namespace", "--source",
                ],
                _ => unreachable!(),
            };
            for &(option, value) in OPTIONS {
                let mut args = base(command);
                args.push(option.into());
                if let Some(value) = value {
                    args.push(value.into());
                }
                assert_eq!(
                    parse(command, &args).is_ok(), expected.contains(&option),
                    "{command} {option}"
                );
            }
        }
    }

    #[test]
    fn unknown_and_misspelled_options_are_never_ignored() {
        for &command in COMMANDS {
            for option in ["--soruce", "--limt", "--top-k", "--targetnamespace", "--help", "--kind=x"] {
                let mut args = base(command);
                args.push(option.into());
                assert!(parse(command, &args).is_err(), "{command} {option}");
            }
        }
    }

    #[test]
    fn every_value_option_rejects_missing_option_and_empty_values() {
        for &command in COMMANDS {
            for &(option, value) in OPTIONS {
                if value.is_none() || !allowed(command, option) {
                    continue;
                }
                for following in [None, Some("--source"), Some("--misspelled"), Some("--"), Some("")] {
                    let mut args = base(command);
                    args.push(option.into());
                    if let Some(following) = following {
                        args.push(following.into());
                    }
                    assert!(parse(command, &args).is_err(), "{command} {option} {following:?}");
                }
            }
        }
    }

    #[test]
    fn strict_positional_arity_for_every_command() {
        for &command in COMMANDS {
            let mut extra = base(command);
            extra.push("extra".into());
            assert!(parse(command, &extra).is_err(), "{command} extra");
            if !matches!(command, "packs" | "inspect") {
                assert!(run(command, &[]).is_err(), "{command} missing");
                let mut empty = base(command);
                empty[0].clear();
                assert!(parse(command, &empty).is_err(), "{command} empty");
            }
        }
        for values in [&["k", "n"][..], &["k", "n", "v", "extra"][..]] {
            assert!(run("related", values).is_err());
        }
        for values in [&["", "n", "v"][..], &["k", "", "v"][..], &["k", "n", ""][..]] {
            assert!(run("related", values).is_err());
        }
    }

    #[test]
    fn dash_positionals_and_end_of_options_are_unambiguous() {
        assert_eq!(run("lookup", &["-q"]).unwrap().positionals, ["-q"]);
        assert_eq!(run("lookup", &["--", "--kind"]).unwrap().positionals, ["--kind"]);
        assert_eq!(run("lookup", &["--", "--"]).unwrap().positionals, ["--"]);
        assert_eq!(run("related", &["--", "--kind", "-ns", "--value"]).unwrap().positionals,
            ["--kind", "-ns", "--value"]);
        assert!(run("lookup", &["--"]).is_err());
        assert!(run("lookup", &["q", "--", "--source", "pack"]).is_err());
    }

    #[test]
    fn options_and_sources_can_precede_or_follow_the_query() {
        let parsed = run("search", &[
            "--source", "b", "--kind", "character", "query", "--source", "a,b",
            "--namespace", "custom", "--limit", "7",
        ]).unwrap();
        assert_eq!(parsed.positionals, ["query"]);
        assert_eq!(parsed.sources, ["b", "a"]);
        assert_eq!(parsed.kind.as_deref(), Some("character"));
        assert_eq!(parsed.namespace.as_deref(), Some("custom"));
        assert_eq!(parsed.limit, 7);
    }

    #[test]
    fn limits_reject_out_of_range_nonintegers_and_overflow() {
        for command in ["search", "related", "resolve-tag", "retrieve"] {
            let names: &[&str] = if matches!(command, "search" | "retrieve") {
                &["--limit", "--topk"]
            } else {
                &["--limit"]
            };
            for &name in names {
                for value in ["0", "101", "-1", "abc", "1.0", "10x", " 10", "10 ", "4294967296"] {
                    let mut args = base(command);
                    args.extend(strings(&[name, value]));
                    assert!(parse(command, &args).is_err(), "{command} {name} {value}");
                }
                for (value, expected) in [("1", 1), ("100", 100), ("01", 1)] {
                    let mut args = base(command);
                    args.extend(strings(&[name, value]));
                    assert_eq!(parse(command, &args).unwrap().limit, expected);
                }
            }
        }
    }

    #[test]
    fn limit_aliases_and_repetitions_must_agree() {
        for command in ["search", "retrieve"] {
            for (first, second) in [("--limit", "--topk"), ("--topk", "--limit"), ("--limit", "--limit"), ("--topk", "--topk")] {
                assert_eq!(run(command, &["q", first, "05", second, "5"]).unwrap().limit, 5);
                assert!(run(command, &["q", first, "5", second, "6"]).is_err());
            }
        }
    }

    #[test]
    fn target_namespace_aliases_and_repetitions_must_agree() {
        for command in ["ask", "resolve-tag"] {
            for (first, second) in [
                ("--target-namespace", "--target-tag-namespace"),
                ("--target-tag-namespace", "--target-namespace"),
                ("--target-namespace", "--target-namespace"),
            ] {
                assert_eq!(run(command, &["q", first, "custom:tag", second, "custom:tag"])
                    .unwrap().target_namespace.as_deref(), Some("custom:tag"));
                assert!(run(command, &["q", first, "a", second, "b"]).is_err());
            }
        }
    }

    #[test]
    fn source_lists_flatten_and_deduplicate_without_reordering() {
        let parsed = run("inspect", &["--source", "b,a,b", "--source", "c,a", "--source", "b"]).unwrap();
        assert_eq!(parsed.sources, ["b", "a", "c"]);
        assert!(run("inspect", &[]).unwrap().sources.is_empty());
        assert!(run("packs", &["--source", "a"]).is_err());
    }

    #[test]
    fn explicit_empty_source_selection_is_never_all_sources() {
        for value in ["", ",", ",a", "a,", "a,,b", "a, ,b"] {
            assert!(run("inspect", &["--source", value]).is_err(), "{value:?}");
            assert!(run("inspect", &["--source", "valid", "--source", value]).is_err());
        }
    }

    #[test]
    fn source_ids_use_the_manifest_safe_ascii_boundary() {
        for value in [".", "..", "a/b", "a\\b", "../escape", "a b", "a\n", "中文", "a:b", "a+b", "a\0b"] {
            assert!(run("inspect", &["--source", value]).is_err(), "{value:?}");
        }
        assert!(run("inspect", &["--source", &"a".repeat(129)]).is_err());
        assert_eq!(run("inspect", &["--source", &"a".repeat(128)]).unwrap().sources[0].len(), 128);
        for value in ["A_custom-1.pack", "-pack", "_pack", ".pack", "123"] {
            assert_eq!(run("inspect", &["--source", value]).unwrap().sources, [value]);
        }
    }

    #[test]
    fn exact_key_requires_both_filters_before_runtime_access() {
        for command in ["lookup", "resolve-tag"] {
            for values in [&["q", "--key"][..], &["q", "--key", "--kind", "k"][..], &["q", "--key", "--namespace", "n"][..]] {
                assert_eq!(run(command, values).unwrap_err().to_string(), "exact key requires --kind and --namespace");
            }
            assert!(run(command, &["q", "--key", "--kind", "k", "--namespace", "n", "--key"]).unwrap().key);
            assert!(run(command, &["q", "--key", "true", "--kind", "k", "--namespace", "n"]).is_err());
        }
        for values in [&["v"][..], &["v", "--kind", "k"][..], &["v", "--namespace", "n"][..]] {
            assert!(run("related", values).is_err());
        }
    }

    #[test]
    fn related_supports_both_forms_and_both_directions() {
        for direction in ["out", "in"] {
            let key = run("related", &["value", "--kind", "character", "--namespace", "custom", "--relation", "member_of", "--filter", "tag", "--direction", direction]).unwrap();
            assert_eq!(key.positionals, ["value"]);
            assert_eq!(key.kind.as_deref(), Some("character"));
            assert_eq!(key.namespace.as_deref(), Some("custom"));
            assert_eq!(key.filter.as_deref(), Some("tag"));
            assert_eq!(key.relation.as_deref(), Some("member_of"));
            assert_eq!(key.direction, direction);
            let legacy = run("related", &["character", "custom", "value", "--kind", "tag", "--direction", direction]).unwrap();
            assert_eq!(legacy.positionals, ["character", "custom", "value"]);
            assert_eq!(legacy.kind.as_deref(), Some("tag"));
            assert!(legacy.namespace.is_none());
            assert_eq!(legacy.direction, direction);
        }
        assert_eq!(run("related", &["k", "n", "v"]).unwrap().direction, "out");
    }

    #[test]
    fn related_legacy_destination_filters_cannot_silently_conflict() {
        assert_eq!(run("related", &["k", "n", "v", "--filter", "tag"]).unwrap().filter.as_deref(), Some("tag"));
        assert!(run("related", &["k", "n", "v", "--kind", "tag", "--filter", "tag"]).is_ok());
        assert!(run("related", &["k", "n", "v", "--kind", "tag", "--filter", "page"]).is_err());
        assert!(run("related", &["k", "n", "v", "--namespace", "other"]).is_err());
    }

    #[test]
    fn wrong_or_conflicting_direction_is_a_usage_error() {
        for value in ["IN", "OUT", "both", "backward", "", "1"] {
            for mut args in [base("related"), strings(&["k", "n", "v"])] {
                args.extend(strings(&["--direction", value]));
                assert!(parse("related", &args).is_err());
            }
        }
        assert!(run("related", &["k", "n", "v", "--direction", "out", "--direction", "in"]).is_err());
    }

    #[test]
    fn category_is_an_exact_signed_i64() {
        for (value, expected) in [("-1", -1), ("0", 0), ("+3", 3), ("9223372036854775807", i64::MAX), ("-9223372036854775808", i64::MIN)] {
            assert_eq!(run("resolve-tag", &["q", "--category", value]).unwrap().category, Some(expected));
        }
        for value in ["1.0", "2x", " 3", "3 ", "9223372036854775808", "-9223372036854775809"] {
            assert!(run("resolve-tag", &["q", "--category", value]).is_err());
        }
        assert!(run("resolve-tag", &["q", "--category", "1", "--category", "2"]).is_err());
    }

    #[test]
    fn filters_are_verbatim_not_an_identity_whitelist() {
        let parsed = run("ask", &[" query ", "--kind", "未来-kind", "--namespace", "custom:命名/空間", "--target-namespace", "-target"] ).unwrap();
        assert_eq!(parsed.positionals, [" query "]);
        assert_eq!(parsed.kind.as_deref(), Some("未来-kind"));
        assert_eq!(parsed.namespace.as_deref(), Some("custom:命名/空間"));
        assert_eq!(parsed.target_namespace.as_deref(), Some("-target"));
        assert!(run("lookup", &["q", "--kind", "k", "--kind", "other"]).is_err());
        assert!(run("lookup", &["q", "--namespace", "n", "--namespace", "other"]).is_err());
        assert!(run("related", &["k", "n", "v", "--relation", "r", "--relation", "other"]).is_err());
        assert!(run("related", &["k", "n", "v", "--filter", "tag", "--filter", "page"]).is_err());
    }

    #[test]
    fn usage_error_has_actual_display_debug_and_downcast_support() {
        let error = run("lookup", &["q", "--typo"]).unwrap_err();
        assert_eq!(error.to_string(), "unrecognized arguments for lookup: --typo");
        assert_eq!(format!("{error:?}"), "UsageError(\"unrecognized arguments for lookup: --typo\")");
        let boxed: Box<dyn std::error::Error> = Box::new(error);
        assert!(boxed.downcast_ref::<UsageError>().is_some());
        assert!(boxed.source().is_none());
        assert_eq!(run("lookup", &["q", "--kind"]).unwrap_err().to_string(), "argument --kind: expected a value");
    }
}
