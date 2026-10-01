# ExeFS `.code` function symbol information (two systems)

The `.code` binary itself is fully stripped of symbols (no mangled names,
RTTI, source paths, assert strings, or export table), but the internal
engine embeds class-name tags through two separate systems.

## 1. Profiler name-tag strings

Fully-qualified name strings such as `void menu::town::TownItemMenu::onOpen()`
exist in a block of roughly 216 entries. Each string is referenced by
pointer from the literal pool at the start of the corresponding
constructor/method, in a typical pattern:

```arm
mov  r1, 0
str  r1, [r0, 0xa08]
strb r1, [r0, 0xa0d]
ldr  r1, [pc, ...]   ; = "menu::battle::BattleCommandMenu::BattleCommandMenu()"
ldr  r2, [pc, ...]   ; = vtable pointer
str  r1, [r0, 0xa00] ; this+0xa00 = profiler name pointer
str  r2, [r0]        ; this+0 = vtable
bx   lr
```

This tag is attached only to `menu::`-family UI classes (and the internal
debug menu); classes for the field/battle logic itself carry no tag.

## 2. Class registration table

A fixed table of consecutive 16-byte entries (roughly 96 entries, the
majority of which have a vtable):

```
+0x00  char*  name    (fully-qualified class name + constructor name string)
+0x04  void*  ctor    (pointer to the constructor body)
+0x08  u32    unknown (a value pointing outside the code region; possibly an RVA
                        in a different segment, or an ID — undeciphered)
+0x0c  void*  vtable  (pointer to the vtable body)
```

Because name→ctor→vtable correspond deterministically, every virtual method
can be labeled `<class>::vf<n>` starting from the vtable.

## Known limitations

- The tag exists only for `menu::`-family UI classes; field/battle-logic
  classes remain unnamed
- The meaning of the registration table's `+0x08` field is undeciphered
- To identify symbols for the field/battle logic itself, one must start
  from a UI-layer class and trace callers (e.g. tracing the callers of a
  message-window creation function back to the event trigger handling,
  etc.)
