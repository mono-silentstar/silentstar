# MEMORY COMMAND GUIDE

Use `./memoryctl` for on-demand memory reads/writes.

Core rules:
- Prefer this command surface over free-form filesystem/database exploration.
- Keep calls sparse: 1 call is ideal, 2 calls max unless truly needed.
- Every command returns JSON.
- Primary DB is reliable memory; inferred memory is kept in a separate experimental DB.

Read commands:
- `./memoryctl recent --limit 10`
- `./memoryctl search --query "topic words" --limit 12 --scope all`
- `./memoryctl thread --turn-id <turn_id>`
- `./memoryctl plans --state open --limit 20`
- `./memoryctl plans --state open --include-inferred --limit 20`
- `./memoryctl get --id event:<id>`
- `./memoryctl get --id message:<id>`
- `./memoryctl get --id plan:<plan_id> --include-inferred`

Write commands:
- `./memoryctl note-add --text "fact to remember" --kind preference --tags profile,style`
- `./memoryctl note-add --text "sensitive fact" --secret`
- `./memoryctl note-archive --id <event_id> --reason "superseded"`
- `./memoryctl plan-add --text "Book dentist Monday at 11am"`
- `./memoryctl plan-close --match "book dentist" --status done`
- `./memoryctl feedback-add --target-id event:<id> --signal useful`

Maintenance:
- `./memoryctl sync` refreshes explicit/inferred plan state from message history.

Practical behavior:
- `plan-add` creates explicit plans (stable).
- Plain inferred plan traces are tracked in the experimental inferred DB.
- Use `--include-inferred` only when uncertain/tentative planning context is needed.
