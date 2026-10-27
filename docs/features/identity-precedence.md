# Identity Precedence

Patina resolves people from many sources (Slack, Outlook, calendar). Each
source identifies a person in a different way, so entity resolution needs one
fixed answer to "which identifier wins?". That answer is
`IDENTIFIER_PRECEDENCE` in `src/patina/graph.py`. It is defined once, and every
consumer derives its ordering from it.

## Precedence order

Strongest first:

| Rank | Type           | Example                                       |
|------|----------------|-----------------------------------------------|
| 0    | `slack_id`     | `U0000000A1`                                  |
| 1    | `dn` (full DN) | `/O=EXAMPLEORG/OU=X/CN=RECIPIENTS/CN=DBROOK`  |
| 2    | `email`        | `dbrook@example.com`                          |
| 3    | `handle`       | `dbrook`                                      |
| 4    | `display_name` | `Dana Brook`                                  |

`identifier_type(name)` classifies a token as one of these types, and
`identifier_rank(name)` returns its index (0 is strongest).

Classification checks, in this order:

1. A token starting with `/O=` is a full DN only if it has a `CN=` component
   (at the start or right after a `/`). Otherwise it is a truncated DN (see
   below).
2. Any other token containing `CN=` is a DN.
3. A token with a space is a display name.
4. A token with `@` is an email.
5. A token matching the Slack user/workspace ID pattern is a Slack ID.
6. Anything else is a handle.

## Truncated DNs are never identifiers

A legacy Exchange DN cut off before its `CN=` component, such as
`/O=EXAMPLEORG` or `/O=EXAMPLEORG/OU=X`, names an organisation, not a person.
Many unrelated senders share it. `identifier_type` returns `None` for it, and
`identifier_rank` ranks it after every identifier. As a result:

- `resolve_entity_id` returns `None` for a truncated-DN name, and skips
  truncated-DN aliases when matching.
- `find_dedup_candidates` / `dedup_entities` never group entities on a shared
  truncated DN.
- `repair_multi_identity_names` uses a truncated DN (or the neutral
  `/O=SINK/<id>` label) as the name of a multi-identity sink, because that
  name cannot claim any member's identity.
- `_name_type_rank` never ranks a truncated DN above an identifier. It shares
  the last slot with the full DN.

## Consumers

- **`resolve_entity_id`** (`graph.py`) resolves Slack IDs first (phase 2).
  Phase 5 tries the remaining aliases in precedence order: full DN, then email,
  then handle, then display name. If every alias matches a different entity,
  the strongest type wins.
- **Ingest** (`ingest.py`) builds sender entities with
  `extract_sender_entity` and stores them with `upsert_entity`. Both call
  `resolve_entity_id`, so ingest follows the same contract and has no ordering
  of its own.
- **`split_dn_sink`** (`maintenance.py`) routes each observation by its
  strongest available key: `sender_slack_id`, then `sender_dn`. The calendar
  organizer, a display name, is tried last. For each full-DN alias, the
  trailing SMTP address (email) is tried before the trailing handle.
- **`dedup_entities`** and **`repair_multi_identity_names`** use
  `_name_type_rank` and the shared truncated-DN rule.

## Display-label rank

`_name_type_rank` picks which name an entity *displays*, not which identifier
*matches*. It is used by `upsert_entity` and by the dedup survivor choice. Its
order is derived from `IDENTIFIER_PRECEDENCE`:

- Human-readable types in reverse precedence: display name (0), handle (1),
  email (2). Weaker identifiers are friendlier labels.
- Then opaque machine IDs in precedence order: Slack ID (3), DN (4).

The maintenance copy is a thin wrapper around the graph function. It also
requires a spaced name to pass `is_plausible_person_name`. A spaced token that
fails this check (e.g. `the quick fox`) ranks as an email or handle instead.

## Normalization

Tokens are normalized before they are compared, so variants of the same
identifier match one entity:

- **`slack:` prefix**: `normalize_alias` strips any platform prefix before
  the first `:`. So `slack:U0000000A1` and `U0000000A1` are the same Slack ID
  in `resolve_entity_id`. `_name_type_rank` classifies the raw stored token.
- **`@handle`**: `normalize_name` strips a leading `@`, so `@dbrook` and
  `dbrook` match the same entity. For an email, `normalize_name` keeps only
  the local part (`dbrook@example.com` → `dbrook`).
- **`Last, First`**: `normalize_name` reorders `Brook, Dana` to `dana brook`.
  `extract_sender_entity` stores a `Last, First` sender as `Dana Brook` and
  keeps the original form as an alias.
