## Latest Changes

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