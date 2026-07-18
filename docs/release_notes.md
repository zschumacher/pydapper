## Latest Changes

* chore(ai): Add CLAUDE.md symlink to AGENTS.md. PR [#544](https://github.com/zschumacher/pydapper/pull/544) by [@zschumacher](https://github.com/zschumacher).
* fix: harden async context lifecycle. PR [#540](https://github.com/zschumacher/pydapper/pull/540) by [@zschumacher](https://github.com/zschumacher).
* fix: harden async context lifecycle. Async resources now resolve exactly once and
  context-manager exception suppression propagates correctly; both `await connect_async()`
  and `async with connect_async()` usage remain unchanged.
* feat: stabilize adapter registration. PR [#539](https://github.com/zschumacher/pydapper/pull/539) by [@zschumacher](https://github.com/zschumacher).

### Breaking Changes

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
