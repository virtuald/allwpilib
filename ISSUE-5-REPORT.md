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

At the original implementation checkpoint, compilation succeeded, but normal
linking was blocked by a host GCC libatomic script referencing a missing shared
library (see ISSUE-2-REPORT.md). This is now resolved; see follow-up below. Focused
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

With **both** this change and its exact item-2 parent, the tested native contract
is that a single Add returning nullptr leaves database state and retained
pointers unchanged, and checked native layout arithmetic rejects overflow.
Downstream candidate rebuilding or overflow inspection used solely for those
contracts can be removed. This does not establish equivalence with any other
downstream validation or publication policy. Consumers still need their own
transaction for atomic groups of additions. Descriptor pointers survive
successful additions/replacements; fields of the replaced schema do not have
that guarantee. Dependent-field pointers survive layout refresh, but consumers
must check IsValid() before using a layout and provide appropriately sized data
after a successful resize.

## Review follow-up: unresolved replacement

Verified the reviewer finding using `Inner = uint8 value`,
`Outer = Inner child`, plus `Right = Inner child` and
`Top = Outer left; Right right; uint8 tail`. Replacing Inner with
`Missing value` succeeds, but previously left Outer, Right, and Top falsely
valid. The new regression failed exactly those three validity assertions before
the fix (Bazel exit 3, `/tmp/issue5-followup-red.log`).

AddImpl now shares its existing visited-dependent invalidation walk between
layout failure and unresolved replacement. It marks all transitive dependents
invalid without rebuilding their fields. The multilevel diamond regression
checks descriptor/dependent-field pointers and later completion with
`Missing = uint32 value`, including refreshed offsets/size and retained-field
codec access. This is an accepted unresolved state, not an Add failure: old
layout metadata may remain stored but is not usable while IsValid() is false.

Fresh verification (GCC 15, Linux x86-64):

* `../../bazelisk test //wpiutil/src/test/native:all --jobs=2`, normal linking
  with libatomic restored: exit **0**, both Bazel test labels pass, **1003 cases /
  23382 assertions** in the full wpiutil native executable.
  Log: `/tmp/issue5-followup-green.log`.
* Actual `-m32` Catch2 build of `DynamicStructTest.cpp` and
  `SchemaParserTest.cpp`, including the new diamond regression: build **0**, run
  **0**, **64 cases / 911 assertions**. `readelf -h` confirms ELF32 / Intel 80386.
  Logs: `/tmp/issue5-followup-real32{,-build}.log`.
* Rebuilt and reran both `/tmp/insertion32.cpp` and `/tmp/layout32.cpp` against
  the current source: each build **0**, each run **0**. Both assert 32-bit size_t.
  Logs: `/tmp/issue5-followup-{insertion,layout}32{,-build}.log`.
* All three 32-bit builds use `-fsanitize=shift
  -fsanitize-undefined-trap-on-error`; these are focused tests, not the whole
  wpiutil suite in 32-bit mode. Use the source/include list above; the Catch2
  run additionally links `/tmp/issue1-catch32/libcatch.a` and native `main.cpp`.

## Measured transaction cost and remaining traversal limitation

Standalone public-API microbenchmark, GCC 15 `-O2 -std=c++23`, Linux x86-64;
median of three fresh-database runs, wall-clock milliseconds for all N Add
calls. Each type has one field. Independent types use `uint8 value`; chain T0
uses the same schema and each Ti uses `T(i-1) child`. The chain is inserted
leaf-first, so these timings isolate insertion/copy cost rather than a later
root-completion propagation. Strings and parsing are included; compilation and
database destruction are excluded. Baseline is exact item-2 parent
`8f88a856de5ead603c56a6e9905c7e21f8db8980`, compiled with identical flags.

| N | Independent baseline | Independent current | Chain baseline | Chain current |
|---:|---:|---:|---:|---:|
| 500 | 0.262 | 18.759 | 0.227 | 51.560 |
| 1000 | 0.315 | 86.021 | 0.488 | 241.799 |
| 2000 | 0.684 | 372.046 | 0.967 | 984.027 |
| 4000 | 1.398 | 1591.870 | 2.019 | 3980.718 |

Build/run exits were **0** for both versions. Raw results:
`/tmp/issue5{,-baseline}-benchmark.csv`; harness:
`/tmp/issue5-benchmark.cpp`. Reproduction harness:

```cpp
#include "wpi/util/struct/DynamicStruct.hpp"
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <string>
using namespace wpi::util;
int main() {
  for (bool chain : {false, true}) {
    for (int n : {500, 1000, 2000, 4000}) {
      for (int rep = 0; rep < 3; ++rep) {
        StructDescriptorDatabase db;
        std::string err;
        auto start = std::chrono::steady_clock::now();
        for (int i = 0; i < n; ++i) {
          auto schema = chain && i ? "T" + std::to_string(i-1) + " child"
                                   : "uint8 value";
          if (!db.Add("T" + std::to_string(i), schema, &err)) std::abort();
        }
        auto ms = std::chrono::duration<double, std::milli>(
            std::chrono::steady_clock::now()-start).count();
        std::printf("%s,%d,%d,%.3f\n", chain ? "chain" : "independent",
                    n, rep, ms);
      }
    }
  }
}
```

Compile using the source/include list from the 32-bit command in
ISSUE-2-REPORT.md, replacing `/tmp/layout32.cpp` with this harness, removing
`-m32`, and adding `-O2`. For baseline replace DynamicStruct.cpp with
`git show 8f88a856de5ead603c56a6e9905c7e21f8db8980:wpiutil/src/main/native/cpp/struct/DynamicStruct.cpp`.

Copying/remapping every existing descriptor, field, schema, and reverse edge
costs O(graph storage) time and temporary memory **per insertion**, in addition
to validation and replay. Removing stale dependency edges also scans the graph.
For bounded-size independent schemas (or this chain), aggregate insertion is
O(N²), consistent with roughly fourfold time on doubling N. At N=4000 the
measured slowdowns are about 1139x independent and 1972x chain versus the very
small baseline. This is not a cheap transaction implementation for large schema
registries. It buys an auditable preflight and stable live pointers without a
rollback journal; accepting that cost is an explicit tradeoff, not a performance
claim. Incremental transaction design remains outside this follow-up.

Existing CheckCircular and CalculateOffsets recursively follow reverse edges
without a global visited set. Multiple fields referring to the same type create
repeated reverse edges; reconvergent diamonds can multiply traversed paths
exponentially, and deep chains can exhaust the call stack. This predates the
copy transaction, which repeats validation work, and is **not fixed here**.
The new invalidation walk visits each affected descriptor once, but its linear
membership search can itself cost O(V*E); it does not make later cycle/layout
walks linear. These benchmarks do not represent adversarial diamonds or repeated
edges. The small diamond test establishes correctness/recovery, not scalability.
Deduplicating edges or redesigning propagation is deferred rather than bundled
into the atomicity fix.
