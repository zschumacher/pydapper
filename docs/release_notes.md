## Latest Changes

* v1: adapters are now discovered through the standard `pydapper.adapters` entry-point group and load lazily.
  First-party and third-party adapters use one provider contract: an installed distribution declares an entry point
  per adapter name whose synchronous zero-argument callback registers exactly that name through the public
  `register_adapter()`. The eight stable first-party names (`sqlite3`, `psycopg2`, `psycopg`, `aiopg`, `mysql`,
  `pymssql`, `oracledb`, `google`) are unchanged and are now declared by the `pydapper` distribution itself; the
  private eager first-party bootstrap was removed, so a plain `import pydapper` no longer registers adapters,
  imports adapter command modules, or imports optional database drivers. DSN-based `connect()` / `connect_async()`
  and explicit `using(..., adapter=name)` / `using_async(..., adapter=name)` selection load only the requested
  provider (explicit selection still bypasses connection predicates), while automatic `using()` / `using_async()`
  selection loads every installed provider before evaluating predicates, so an unrelated broken provider can fail
  automatic selection but never exact-name selection. Precedence is deterministic: a direct runtime
  `register_adapter()` call wins for the process, the first-party provider wins over an external provider using the
  same name, and duplicate external providers fail before either loads with every conflicting distribution named —
  metadata enumeration order never chooses a winner. Provider failures identify the adapter and provider
  distribution, preserve the original exception as the cause, and roll back their registry mutations; successful
  callbacks run at most once per process and the installed catalog is cached per process. Runtime registration via
  `register_adapter()` remains fully supported, no public API is added or deprecated, and no new runtime dependency
  is introduced. See [Adapter registration](adapter_registration.md) for the packaging contract for adapter authors.
* feat: extract first-party adapter provider callbacks. PR [#563](https://github.com/zschumacher/pydapper/pull/563) by [@zschumacher](https://github.com/zschumacher).
* feat: load installed adapter providers before automatic selection. PR [#562](https://github.com/zschumacher/pydapper/pull/562) by [@zschumacher](https://github.com/zschumacher).
* feat: add private deterministic load-all-providers pass. PR [#561](https://github.com/zschumacher/pydapper/pull/561) by [@zschumacher](https://github.com/zschumacher).
* feat: resolve installed adapter providers from name-based public paths. PR [#560](https://github.com/zschumacher/pydapper/pull/560) by [@zschumacher](https://github.com/zschumacher).
* feat: add private exact-name adapter resolution and provider precedence. PR [#559](https://github.com/zschumacher/pydapper/pull/559) by [@zschumacher](https://github.com/zschumacher).
* feat: add private transactional loader for adapter provider entry points. PR [#558](https://github.com/zschumacher/pydapper/pull/558) by [@zschumacher](https://github.com/zschumacher).
* feat: replace dsnparse with an owned URL DSN parser. PR [#557](https://github.com/zschumacher/pydapper/pull/557) by [@zschumacher](https://github.com/zschumacher).
* v1: pydapper now owns its narrow URL-style DSN parser using the standard library's `urllib.parse`. A direct
  implementation is smaller and lower risk than vendoring a generic parser API that pydapper does not consume. This
  removes the mandatory `dsnparse` dependency, so it is no longer installed with pydapper, while preserving default and
  exact explicit adapter routing, including third-party adapters. Parse-result fields now have accurate public types,
  and representations and parser-generated errors no longer expose credential-bearing DSNs or passwords. Decoded
  network hosts are revalidated so encoded controls and Unicode delimiter lookalikes cannot bypass authority parsing.
* feat: add private lazy entry-point discovery catalog for pydapper.adapters. PR [#556](https://github.com/zschumacher/pydapper/pull/556) by [@zschumacher](https://github.com/zschumacher).
* feat: validate capability declarations and add command preparation hooks. PR [#555](https://github.com/zschumacher/pydapper/pull/555) by [@zschumacher](https://github.com/zschumacher).
* feat: validate adapter capability declarations and add command preparation hooks.
  `register_adapter()` now validates each supplied command class's `capabilities`
  declaration (a `frozenset` of `AdapterCapability` members) for both modes before the
  registry is touched, so an invalid declaration fails atomically. Every first-party
  command class explicitly declares its current — empty — capability set, and
  `commands.supports(AdapterCapability.X)` reports declared support. New documented,
  compatibility-sensitive adapter-author preparation seams run inside the command-owned
  cursor lifecycle for every sync and async command family: `_prepare_cursor*()` once per
  acquired cursor and `_prepare_command*()` once per executed handler, both receiving a
  normalized `CommandOptions` instance. No optional capability (transactions, timeouts,
  stored procedures, readonly, max rows, etc.) is implemented by this change. The
  `*_or_default` helpers now forward the normalized options to `query_first` /
  `query_single`; see **Breaking Changes** below for the subclass-override impact.
* feat: add AdapterCapability vocabulary and command capability checks. PR [#554](https://github.com/zschumacher/pydapper/pull/554) by [@zschumacher](https://github.com/zschumacher).
* test: cover query_multiple runtime failures inside the command-owned cursor lifecycle. PR [#553](https://github.com/zschumacher/pydapper/pull/553) by [@zschumacher](https://github.com/zschumacher).
* fix: project query_single rows inside the command-owned cursor lifecycle. PR [#551](https://github.com/zschumacher/pydapper/pull/551) by [@zschumacher](https://github.com/zschumacher).
* fix: run mysql query_first inside the command-owned cursor lifecycle. PR [#552](https://github.com/zschumacher/pydapper/pull/552) by [@zschumacher](https://github.com/zschumacher).
* fix: project query_single rows inside the command-owned cursor lifecycle. PR [#550](https://github.com/zschumacher/pydapper/pull/550) by [@zschumacher](https://github.com/zschumacher).
* fix: validate and extract scalar results inside the command-owned cursor lifecycle. PR [#549](https://github.com/zschumacher/pydapper/pull/549) by [@zschumacher](https://github.com/zschumacher).
* fix: project query_first rows inside the command-owned cursor lifecycle. PR [#548](https://github.com/zschumacher/pydapper/pull/548) by [@zschumacher](https://github.com/zschumacher).
* fix: async command-owned cursor exception precedence. PR [#547](https://github.com/zschumacher/pydapper/pull/547) by [@zschumacher](https://github.com/zschumacher).
* fix: sync command-owned cursor exception precedence. PR [#546](https://github.com/zschumacher/pydapper/pull/546) by [@zschumacher](https://github.com/zschumacher).
* fix: validate complete query batches before DBAPI work. PR [#545](https://github.com/zschumacher/pydapper/pull/545) by [@zschumacher](https://github.com/zschumacher).
* fix: validate complete query batches before DBAPI work. `query_multiple` and
  `query_multiple_async` now construct and validate every parameter handler before acquiring
  a cursor, so a missing or invalid parameter in any query of the tuple fails before any
  query executes or fetches. This is client-side prevalidation, not transactional execution;
  a validated batch can still fail partway through on a runtime database, fetch, column, or
  mapping error.
* chore(ai): Add CLAUDE.md symlink to AGENTS.md. PR [#544](https://github.com/zschumacher/pydapper/pull/544) by [@zschumacher](https://github.com/zschumacher).
* fix: harden async context lifecycle. PR [#540](https://github.com/zschumacher/pydapper/pull/540) by [@zschumacher](https://github.com/zschumacher).
* fix: harden async context lifecycle. Async resources now resolve exactly once and
  context-manager exception suppression propagates correctly; both `await connect_async()`
  and `async with connect_async()` usage remain unchanged.
* feat: stabilize adapter registration. PR [#539](https://github.com/zschumacher/pydapper/pull/539) by [@zschumacher](https://github.com/zschumacher).

### Breaking Changes

* DSNs now follow the focused `<database>[+<adapter>]://...` v1 grammar. Incidental inherited conveniences such as
  `name=value` strings, constructor default injection, dict-like mutation, tuple-style iteration or indexing,
  environment helpers, and multiple hosts are intentionally not reproduced. Multi-plus input such as
  `db+adapter+extra://...` previously invented the adapter name `adapter_extra`; it is now rejected. Query values are no
  longer implicitly coerced: for example,
  `?code=001&enabled=true` previously produced `1` and `True` but now preserves `"001"` and `"true"`; a bare query key
  such as `?flag` now maps to `{"flag": ""}` instead of raising. Corrected DSN examples place ports after the host;
  literal and percent-encoded colons in passwords remain valid. SQLite slash counts are now explicit:
  `sqlite:///relative/path.db` targets `relative/path.db`; use `sqlite:////absolute/path.db` for `/absolute/path.db`
  (the three-slash form previously targeted `/relative/path.db`).
* Command delegation: `query_first_or_default`, `query_single_or_default`, and their async
  equivalents now forward the normalized `options=` keyword to `query_first` /
  `query_single` (and the async equivalents) instead of validating and discarding it.
  Subclass overrides of those four target methods must accept an `options=` keyword;
  overrides without it now raise `TypeError` when called through the `*_or_default`
  helpers. Add `*, options=None` to the override signature to migrate.
* Adapter registration: `register` and `register_async` were removed. Use [`register_adapter`](adapter_registration.md) and explicit `adapter=` selection where needed.

### Other Changes

* feat: add command options model. PR [#531](https://github.com/zschumacher/pydapper/pull/531) by [@zschumacher](https://github.com/zschumacher).
* docs: define v1 compatibility policy. PR [#530](https://github.com/zschumacher/pydapper/pull/530) by [@zschumacher](https://github.com/zschumacher).
* fix: guarantee query cursor cleanup. PR [#529](https://github.com/zschumacher/pydapper/pull/529) by [@zschumacher](https://github.com/zschumacher).
* docs: clarify mapper references. PR [#528](https://github.com/zschumacher/pydapper/pull/528) by [@zschumacher](https://github.com/zschumacher).
* fix: harden mapper typing ux. PR [#527](https://github.com/zschumacher/pydapper/pull/527) by [@zschumacher](https://github.com/zschumacher).
* fix: handle callable default values safely. PR [#526](https://github.com/zschumacher/pydapper/pull/526) by [@zschumacher](https://github.com/zschumacher).
* fix: reject duplicate query columns. PR [#524](https://github.com/zschumacher/pydapper/pull/524) by [@zschumacher](https://github.com/zschumacher).
* fix: clean up mysql query_single unread results. PR [#523](https://github.com/zschumacher/pydapper/pull/523) by [@zschumacher](https://github.com/zschumacher).
* fix: bound query_single row fetching. PR [#522](https://github.com/zschumacher/pydapper/pull/522) by [@zschumacher](https://github.com/zschumacher).
* fix: harden parameter shapes and executemany behavior. PR [#521](https://github.com/zschumacher/pydapper/pull/521) by [@zschumacher](https://github.com/zschumacher).
* v1: replace placeholder regex with SQL-aware scanner. PR [#509](https://github.com/zschumacher/pydapper/pull/509) by [@zschumacher](https://github.com/zschumacher).
* v1: define public exceptions and cardinality semantics. PR [#505](https://github.com/zschumacher/pydapper/pull/505) by [@zschumacher](https://github.com/zschumacher).
* feat: add params alias across public command APIs. PR [#503](https://github.com/zschumacher/pydapper/pull/503) by [@zschumacher](https://github.com/zschumacher).
* docs: add AI development guidance. PR [#504](https://github.com/zschumacher/pydapper/pull/504) by [@zschumacher](https://github.com/zschumacher).

## 0.13.1
### Internal
* chore(deps): update deps. PR [#428](https://github.com/zschumacher/pydapper/pull/428) by [@zschumacher](https://github.com/zschumacher).

## 0.13.0
### Internal
* chore(deps): upgrade deps. PR [#427](https://github.com/zschumacher/pydapper/pull/427) by [@zschumacher](https://github.com/zschumacher).
* chore: update deps. PR [#384](https://github.com/zschumacher/pydapper/pull/384) by [@zschumacher](https://github.com/zschumacher).
* chore: migrate to use testcontainers. PR [#383](https://github.com/zschumacher/pydapper/pull/383) by [@zschumacher](https://github.com/zschumacher).

## 0.12.0
### Features
* :sparkles: Support psycopg async apis. PR [#336](https://github.com/zschumacher/pydapper/pull/336) by [@zschumacher](https://github.com/zschumacher).

### Bug Fixes
* 🔧 fix sqlite not opening in subdirectories. PR [#344](https://github.com/zschumacher/pydapper/pull/344) by [@arieroos](https://github.com/arieroos).

### Internal
* :wrench: upgrade poetry, actions, and use newer oracle image. PR [#335](https://github.com/zschumacher/pydapper/pull/335) by [@zschumacher](https://github.com/zschumacher).

## 0.11.1
### Features
* :sparkles: Add callable that returns a model as a supported model type. PR [#333](https://github.com/zschumacher/pydapper/pull/333) by [@zschumacher](https://github.com/zschumacher).

## 0.11.0
### Breaking changes
* Python 3.8 support deprecated
* cx_oracle support deprecated

### Internal
* :wrench: update to latest dsnparse. PR [#332](https://github.com/zschumacher/pydapper/pull/332) by [@zschumacher](https://github.com/zschumacher).
* :wrench: support python 3.13; update deps; deprecate Cx_Oracle in favor or Oracledb. PR [#331](https://github.com/zschumacher/pydapper/pull/331) by [@zschumacher](https://github.com/zschumacher).
* Bump idna from 3.4 to 3.7. PR [#262](https://github.com/zschumacher/pydapper/pull/262) by [@dependabot[bot]](https://github.com/apps/dependabot).
* Bump cryptography from 41.0.5 to 42.0.4. PR [#255](https://github.com/zschumacher/pydapper/pull/255) by [@dependabot[bot]](https://github.com/apps/dependabot).

## 0.10.0
### Features
* * ✨ add support for `psycopg3`. PR [#214](https://github.com/zschumacher/pydapper/pull/214) by [@idumancic](https://github.com/idumancic).

### Internal
* 🔧  fix step names in fmt.yml. PR [#256](https://github.com/zschumacher/pydapper/pull/256) by [@otosky](https://github.com/otosky).
* ⬆️ Support python 3.12. PR [#199](https://github.com/zschumacher/pydapper/pull/199) by [@zschumacher](https://github.com/zschumacher).

### Docs
* 📝 Remove broken badge in docs index. PR [#198](https://github.com/zschumacher/pydapper/pull/198) by [@zschumacher](https://github.com/zschumacher).
* 🔧 add readthedoc config file. PR [#197](https://github.com/zschumacher/pydapper/pull/197) by [@zschumacher](https://github.com/zschumacher).

## 0.9.0
### Bug fixes
* Fix unmatched param bug. PR [#162](https://github.com/zschumacher/pydapper/pull/162) by [@bowiec](https://github.com/bowiec).

### Internal
* 🔧 update poetry to 1.7.1 and bump deps. PR [#195](https://github.com/zschumacher/pydapper/pull/195) by [@zschumacher](https://github.com/zschumacher).
* 🔧 use bigquery emulator for tests. PR [#166](https://github.com/zschumacher/pydapper/pull/166) by [@zschumacher](https://github.com/zschumacher).
* 🔧 bump deps and use markers for tests. PR [#164](https://github.com/zschumacher/pydapper/pull/164) by [@zschumacher](https://github.com/zschumacher).

## 0.8.0
### Features
* ✨ Add support for `bigquery`. PR [#142](https://github.com/zschumacher/pydapper/pull/142) by [@zschumacher](https://github.com/zschumacher).

### Internal
* 🔧 Remove python 3.7 support. PR [#145](https://github.com/zschumacher/pydapper/pull/145) by [@zschumacher](https://github.com/zschumacher).
* 🔧 update `poetry` to `1.4.0`. PR [#143](https://github.com/zschumacher/pydapper/pull/143) by [@zschumacher](https://github.com/zschumacher).
* 🔧 Remove irrelevant make command. PR [#125](https://github.com/zschumacher/pydapper/pull/125) by [@zschumacher](https://github.com/zschumacher).
* 🔧 Dependabot 2023-02-12. PR [#124](https://github.com/zschumacher/pydapper/pull/124) by [@zschumacher](https://github.com/zschumacher).

### Docs
* 📋 Add `aiopg` to table in PostgreSQL docs section. PR [#107](https://github.com/zschumacher/pydapper/pull/107) by [@zschumacher](https://github.com/zschumacher).

## 0.7.0
### Features
* 🔧 Improve typing. PR [#101](https://github.com/zschumacher/pydapper/pull/101) by [@zschumacher](https://github.com/zschumacher).

### Internal
* 🔧 Dependabot updates 2023-01-01. PR [#106](https://github.com/zschumacher/pydapper/pull/106) by [@zschumacher](https://github.com/zschumacher).

## 0.6.0
### Features
* ⬆️ support python 3.11. PR [#84](https://github.com/zschumacher/pydapper/pull/84) by [@zschumacher](https://github.com/zschumacher).

## 0.5.3
### Internal
* 🔧 Add variable length tuple typing annotation for query_multiple. PR [#67](https://github.com/zschumacher/pydapper/pull/67) by [@enewnham](https://github.com/enewnham).
* 🔧 Dependabot updates 2022-10-28. PR [#85](https://github.com/zschumacher/pydapper/pull/85) by [@zschumacher](https://github.com/zschumacher).
* 🔧 Better developer support for arm chips. PR [#52](https://github.com/zschumacher/pydapper/pull/52) by [@zschumacher](https://github.com/zschumacher).

## 0.5.2
### Docs
* 🔧 Add example for serializing one-to-many relationships to docs. PR [#44](https://github.com/zschumacher/pydapper/pull/44) by [@zschumacher](https://github.com/zschumacher).

### Internal
* 🔧 Address dependabot 2022-08-13. PR [#51](https://github.com/zschumacher/pydapper/pull/51) by [@zschumacher](https://github.com/zschumacher).
* 🔧 Add extra to install all optional deps. PR [#50](https://github.com/zschumacher/pydapper/pull/50) by [@zschumacher](https://github.com/zschumacher).

## 0.5.1
### Internal
* 🔧 Address Dependabot PRs. PR [#42](https://github.com/zschumacher/pydapper/pull/42) by [@zschumacher](https://github.com/zschumacher).
* 🔧 Add Dependabot. PR [#31](https://github.com/zschumacher/pydapper/pull/31) by [@zschumacher](https://github.com/zschumacher).

## 0.5.0
### Features
* ✨ Add `oracledb` support. PR [#25](https://github.com/zschumacher/pydapper/pull/25) by [@troyswanson](https://github.com/troyswanson).

### Internal
* 🔧 Bump black to the stable release v22.3.0. PR [#27](https://github.com/zschumacher/pydapper/pull/27) by [@zschumacher](https://github.com/zschumacher).
* 🔧  use coro-context-manager. PR [#23](https://github.com/zschumacher/pydapper/pull/23) by [@zschumacher](https://github.com/zschumacher).

## 0.4.0
### Features
* ✨ Add async support starting with `aiopg`. PR [#22](https://github.com/zschumacher/pydapper/pull/22) by [@zschumacher](https://github.com/zschumacher).

## 0.3.0
### Features
* ✨ support `PYDAPPER_DSN` environment variable for connections. PR [#21](https://github.com/zschumacher/pydapper/pull/21) by [@zschumacher](https://github.com/zschumacher).
  
### Internal
* 🔧 Cache oracle-instantclient download in test workflow. PR [#20](https://github.com/zschumacher/pydapper/pull/20) by [@zschumacher](https://github.com/zschumacher).

## 0.2.0
### Features
* ✨ Add oracle support via `cx_Oracle`. PR [#17](https://github.com/zschumacher/pydapper/pull/17) by [@zschumacher](https://github.com/zschumacher).

## 0.1.2
 🚀 First stable release of *pydapper*!
