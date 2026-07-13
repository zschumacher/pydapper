# Compatibility and deprecation policy

This policy defines the public compatibility contract for pydapper 1.x. It
takes effect with the 1.0 release and applies to every 1.x release. The
package is pre-1.0 today, so changes before 1.0 may be breaking; each
intentional v0-to-v1 break will be recorded in the release notes and covered
by the v0-to-v1 migration guide.

## Scope and effective version

pydapper's v1 contract is a small DB-API wrapper. It covers the documented
query, command, parameter, mapping, transaction, adapter, typing, and
agent-safe interfaces as they are released. A roadmap item is not a user
guarantee until it is implemented and documented. This policy does not freeze
the complete list of exports or protocols; the final export and typing audit
belongs to [#484](https://github.com/zschumacher/pydapper/issues/484).

## What is public API

An API is public when pydapper intentionally documents it or exports it as a
supported package-level interface. In particular, the public API includes:

- documented imports from the `pydapper` package root;
- documented methods and properties on command and query objects;
- public function and method signatures, including keyword names and
  supported call patterns;
- documented return types, exceptions, cardinality behavior, row shapes, and
  resource-cleanup behavior;
- public exception classes and their documented machine-readable attributes;
- public types, protocols, overload behavior, and the `py.typed` contract;
- documented SQL placeholder and parameter-binding behavior; and
- documented adapter registration, selection, and capability contracts once
  those features land.

Documentation is the source of truth for whether a symbol or behavior is
supported. An importable name is not public merely because Python permits the
import. The final set of exports and protocols will be audited separately in
[#484](https://github.com/zschumacher/pydapper/issues/484); this page defines
the rule for identifying that set rather than publishing an exhaustive v1
symbol list.

## Internal and provisional interfaces

The following are not compatibility promises unless separately documented as
public:

- names beginning with an underscore;
- internal registries, helpers, sentinels, implementation classes, and module
  layout;
- undocumented direct imports from implementation modules;
- exact exception message text, unless the documentation explicitly promises
  it; and
- incidental behavior inherited from a particular DB-API driver beyond
  pydapper's documented adapter contract.

Experimental or explicitly provisional APIs are also outside the 1.x
compatibility promise. Their documentation must say that they are
experimental or provisional. “Legacy” describes historical usage; it does
not by itself mean that an API is deprecated or scheduled for removal.

## 1.x compatibility rules

pydapper follows semantic-versioning principles for the 1.x line:

- Patch releases may fix bugs and documentation without intentionally
  breaking documented public behavior.
- Minor releases may add backward-compatible APIs and capabilities.
- Removing or incompatibly changing documented public API requires a new major
  release, except where a documented security or correctness emergency makes
  that impossible.
- A bug fix may change behavior that was clearly erroneous or contradicted
  documented behavior. Release notes must call out meaningful compatibility
  impact.

Adapters may differ by declared capabilities. Supported behavior within a
declared capability is part of the compatibility contract for that adapter;
pydapper does not promise that every adapter implements every capability or
that all adapter behavior is identical. An unsupported capability must be
documented and reported according to the adapter contract once that contract
is available.

## Deprecation and removal process

When a public API is deprecated during 1.x:

1. The documentation must identify it as deprecated and name the replacement
   or migration path when one exists.
2. The deprecation must be recorded in the release notes for the release that
   introduces it.
3. User-actionable deprecations and removals must appear in the relevant
   migration guide.
4. The API remains available until at least the next major release.

Runtime `DeprecationWarning` behavior is not automatic policy machinery. It
will be added only through a focused implementation issue, with tests and an
appropriate `stacklevel`. This documentation change adds no warnings.

Removal is a breaking change. It must be called out under a clearly named
**Breaking Changes** section in the release notes and described in the
migration documentation. Security, data-corruption, or similarly severe
cases may require earlier removal; the exception and its user impact must be
explained prominently in both places.

## `params=` and `param=`

`params=` is the preferred v1 spelling and must be used in new documentation
and examples. `param=` remains a supported compatibility alias throughout
the complete 1.x series and is not scheduled for removal before 2.0. This
policy does not add a `DeprecationWarning` for `param=`.

Both spellings have compatible runtime behavior and typing while the alias is
supported. Supplying both spellings is an error and continues to raise the
current clear `ValueError`:

```python
db.query(sql, params={"id": 1})  # preferred

db.query(sql, param={"id": 1})  # supported throughout 1.x

db.query(sql, param={"id": 1}, params={"id": 1})  # error
```

Existing examples and tests that intentionally demonstrate `param=`
compatibility should remain unchanged.

## Recording breaking changes

Every intentional breaking change must have the same record:

- The affected release notes include it under a clearly named **Breaking
  Changes** section.
- The v0-to-v1 migration guide gives a concise before-and-after call pattern
  and the user action required. The full guide is owned by
  [#494](https://github.com/zschumacher/pydapper/issues/494).
- The implementing pull request explains the compatibility impact and links
  the governing issue.
- Adapter-specific breaks identify the affected adapter or package; they must
  not imply that all drivers are affected.
- Typing-only breaks are called out when previously valid typed usage no
  longer type-checks.

Historical release notes remain intact. This policy does not require
rewriting older entries to fit the current format.

## Adapter and typing considerations

Adapter guarantees are capability-scoped: a documented operation is stable
when the selected adapter declares support for it, while unsupported or
adapter-specific behavior must be identified as such. The adapter package
split and the concrete decision about legacy in-core imports such as
`pydapper.postgresql`, `pydapper.mysql`, and `pydapper.sqlite` belong to
[#501](https://github.com/zschumacher/pydapper/issues/501). This policy does
not decide whether those paths are removed, retained, or shimmed.

The `py.typed` marker is part of the public typing contract. Public signatures,
keyword names, overload behavior, protocols, and documented types must be
treated as compatibility-sensitive. The final v1 export and typing surface is
still owned by [#484](https://github.com/zschumacher/pydapper/issues/484).
Command options and any resulting signature changes are owned by
[#502](https://github.com/zschumacher/pydapper/issues/502), not this policy.
