# Item 5: failure-atomic single-schema insertion

Original target: `f592035104e45f2bdf413577779f6a7898e4a3b2`.
Branch: `fix/dynamic-struct-insertion-atomicity`.
Exact required parent: `8f88a856de5ead603c56a6e9905c7e21f8db8980`, on
`fix/dynamic-struct-layout-overflow` (item 2). Integrate that commit first; this
branch includes it. These are separate commits/branches, not independent patches.

## Investigation and API decision

The old Add documentation did not promise atomicity. This is an explicit API
contract improvement, not a claimed violation of a previously documented
transaction guarantee. Actual mutation damage was reproduced: rejected duplicate
fields left a partial type; rejected cycles left dependency edges; failed
redefinition destroyed retained fields; failed dependency overflow invalidated
previously valid types. Two new test cases fail with 10 assertions on the item-2
implementation. The initial reproduction also aborted when using a damaged field;
the regression now checks pointer preservation before accessing it.

Add now validates on an isolated copy of the graph, remapping all parent, nested
struct and reverse-dependency pointers. Only a successful validation is replayed
on the live graph. **The candidate is never published or swapped into place.**
Live descriptor addresses remain stable, and unrelated field vectors are not
replaced. Schema replacement removes the old outgoing dependency edges to avoid
stale cycles. Successful replacement of a schema may still invalidate that
schema's own field pointers, as before; its descriptor address stays stable.

The documented guarantee is unchanged database state when Add returns nullptr.
It is single-operation atomicity, not a batch transaction or a new guarantee for
allocation exceptions/concurrent mutation. Validation uses O(database size)
temporary storage and repeats parsing on success; this favors simple, auditable
correctness over an incremental rollback journal. No public transaction API,
serialization changes, or Python policies were introduced.

## Verification

Linux x86-64, GCC 15:

* Item-2 baseline: 1000 test cases / 23258 assertions passed.
* New regression red: 2 cases failed, 10 assertions failed
  (`/tmp/issue5-red.log`).
* Green: **1002 cases / 23351 assertions passed**, entire wpiutil native Catch2
  executable, with the changed DynamicStruct translation unit built using
  `-fsanitize=shift -fsanitize-undefined-trap-on-error`
  (`/tmp/issue5-green.log`).
* A real GCC `-m32` executable with a sizeof(size_t)==4 static assertion passed
  multiplication/addition and dependent overflow, cycle and duplicate recovery,
  zero-size completion, retained descriptor/field/codec access across failure
  and success, zero-size arrays, and exact UINT32_MAX layouts. Shift trap
  instrumentation was enabled; exit status 0 (`/tmp/issue5-32-build.log`).
* `git diff --check` passes.

The committed native tests cover the required empty-Inner overflow recovery,
cycle recovery, duplicate recovery, unrelated retained codec, successful
insertion pointer stability, rejected valid-schema replacement, rejected
previously-valid dependency resize, and stale dependency replacement. The full
suite includes the item-2 layout boundaries, bitfield transitions and ordinary
nesting/array regressions.

Normal Bazel baseline command (max two jobs):

```
../../bazelisk test //wpiutil/src/test/native:all --jobs=2
```

Compilation succeeded, but normal linking is blocked by a host GCC libatomic
script referencing a missing shared library (see ISSUE-2-REPORT.md). Focused
native alternative: reuse those generated native-suite objects; compile only
this branch's changed test/implementation translation units with
`g++ -std=c++23 -fPIC`, include directories
`wpiutil/src/main/native/include`,
`wpiutil/src/main/native/thirdparty/llvm/include`, and
`thirdparty/catch2/src/main/native/include`. Add shift trap flags to the
implementation. In the generated link response file, remove unused `-latomic`,
replace DynamicStructTest.pic.o with `/tmp/issue5-test.o`, insert
`/tmp/issue5-impl.o` before libwpiutil.a, and set output to `/tmp/issue5-tests`.
Then from the item-2 Bazel execution root:

```
gcc @/tmp/issue5-green-link.params
/tmp/issue5-tests > /tmp/issue5-green.log 2>&1
```

The 32-bit focused build uses `/tmp/insertion32.cpp` and the source/include list
in ISSUE-2-REPORT.md, adding `-fsanitize=shift
-fsanitize-undefined-trap-on-error`; output `/tmp/insertion32`. It is a focused
public-API assertion test, not a claim that the entire suite ran in 32-bit mode.

## Downstream impact

With **both** this commit and its exact item-2 parent, downstream candidate
rebuilding and post-layout overflow inspection are unnecessary for a single
native Add operation. Consumers still need their own transaction when publishing
a group of mutually dependent schema additions atomically. No descriptor-by-name
wrapper is needed merely to preserve native pointer lifetime across insertions.
