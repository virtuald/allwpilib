# Item 1: platform-sized dynamic-struct array lengths

## Finding and fix

Base: `f592035104e45f2bdf413577779f6a7898e4a3b2`.
Confirmed defect, reproduced on a real Linux i386 executable: the parser accepts
`char text[4294967296]` and `char text[4294967297]` because conversion to
`uint64_t` succeeds before assignment truncates into `size_t` (zero and one).
`UINT64_MAX` is also incorrectly accepted on i386.

`Parser::ParseDeclaration` now uses `parse_integer<size_t>`. That existing helper
retains the wide parsed value, checks conversion by round-trip comparison, and
returns `nullopt` on overflow before the parser assigns the extent. No new helper,
ABI change, layout policy, or allocation limit is introduced.

Values above `uint64_t`, including 2^64 and much longer decimal strings, were
already rejected; regression tests preserve this. Tests also cover UINT32_MAX,
UINT64_MAX where representable, ordinary arrays, singleton/leading-zero syntax,
and the existing negative/zero/malformed cases. Tests only parse metadata, never
allocate the declared payload.

A failed parse can leave a partially populated declaration (type/name and default
arraySize=1) in the output vector: Parse emplaces before parsing. It returns false,
not success with a default extent. StructDescriptorDatabase::Add checks this
result before creating descriptors. This pre-existing partial-output behavior is
unchanged; callers must honor the boolean result.

## Validation

Host: Fedora 43 Linux x86-64, GCC 15.3.1; actual `-m32` i386 execution on the same
host. `readelf -h /tmp/issue1-parser32` confirmed ELF32, Intel 80386.

Initial native linking was blocked by missing `/usr/lib64/libatomic.so.1.2.0`;
initial `g++ -m32` compilation by missing `gnu/stubs-32.h`. Resolved with:

```sh
dnf install -y glibc-devel.i686 libstdc++-devel.i686 libatomic
```

Native baseline and final command (from this worktree):

```sh
../../bazelisk test //wpiutil/src/test/native:wpiutil_tests --jobs=2 > /tmp/issue1-bazel-green.log 2>&1
```

- Baseline: 998 cases, 23235 assertions passed (baseline log used suffix `baseline`).
- Final: 1001 cases, 23254 assertions passed, including the whole wpiutil native suite.
- No repository-wide, other-module, Windows, ARM, or full i386 wpiutil suite run.

The focused i386 parser suite was built directly from the same production source
and committed Catch2 tests. Build recipe (Catch2 compiled with at most two jobs):

```sh
mkdir -p /tmp/issue1-catch32
find thirdparty/catch2/src/main/native/cpp -name '*.cpp' -print0 |
  xargs -0 -P2 -I{} bash -c 'g++ -m32 -std=c++23 -O0 -Ithirdparty/catch2/src/main/native/include -c "$1" -o "/tmp/issue1-catch32/$(basename "$1").o"' _ {}
ar rcs /tmp/issue1-catch32/libcatch.a /tmp/issue1-catch32/*.o
g++ -m32 -std=c++23 -O0 -Ithirdparty/catch2/src/main/native/include \
  -Iwpiutil/src/main/native/include -Iwpiutil/src/main/native/thirdparty/llvm/include \
  wpiutil/src/test/native/cpp/main.cpp \
  wpiutil/src/test/native/cpp/struct/SchemaParserTest.cpp \
  wpiutil/src/main/native/cpp/struct/SchemaParser.cpp \
  /tmp/issue1-catch32/libcatch.a -o /tmp/issue1-parser32
readelf -h /tmp/issue1-parser32
/tmp/issue1-parser32
```

Build/run output was redirected to `/tmp/issue1-32-{baseline,red,green}.log`
(baseline execution separately in `issue1-32-baseline-run.log`).
- Baseline: 24 cases, 95 assertions passed.
- Red, before implementation: 1 of 27 cases failed, 6 failed assertions: accepted
  all three out-of-platform extents and returned no error (exit 42).
- Green: 27 cases, 111 assertions passed (exit 0).
- `git diff --check`: clean.

## Compatibility and downstream status

Only previously truncated out-of-range lengths on narrow platforms change from
acceptance to rejection. Existing diagnostic style and legal grammar remain.
The downstream original-token scan for item 1 can be removed once the commit
containing this report and parser fix is integrated into the linked native
library. No commits for items 2–6 are required for this particular workaround;
layout-arithmetic checks remain a separate item and are not solved here.
