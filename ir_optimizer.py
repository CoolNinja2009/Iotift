"""
IOTIFT IR Optimizer — Milestone 2

Optimization passes over the IR:
  1. Constant Folding
  2. Dead Code Elimination (DCE)
  3. Empty Handler Removal
  4. Stack Promotion (global → stack-local)
  5. Redundant Store Elimination
"""

from __future__ import annotations
from typing import Optional, List, Dict, Set, Any
from ir import (
    IRModule, IRFunction, IRGlobal,
    BasicBlock, IRValue,
    IRLabel, IRBinary, IRUnary, IRCopy, IRLoad, IRStore,
    IRCall, IRCallIndirect, IRBranch, IRJump, IRReturn,
    IRCast, IRArrayAccess, IRMemberAccess, IRInstr,
    _cv, _vv, _gv, _void,
)


class IROptimizer:
    """Runs a sequence of optimization passes over an IRModule."""

    def __init__(self, module: IRModule):
        self.module = module

    def run_all(self) -> IRModule:
        """Run all optimization passes."""
        self.constant_folding()
        self.copy_propagation()
        self.dead_temp_elimination()
        self.dead_code_elimination()
        self.empty_handler_removal()
        self.redundant_store_elimination()
        # Stack promotion disabled until fully debugged
        # self.stack_promotion()
        return self.module

    # ─────────────────────────────────────────
    #  PASS 1: CONSTANT FOLDING
    # ─────────────────────────────────────────

    def constant_folding(self) -> None:
        """
        Evaluate constant expressions at compile time.
        Example: t1 = 1 + 2  →  t1 = 3
        """
        for fn in self.module.functions:
            for bb in fn.blocks:
                new_instrs = []
                for instr in bb.instructions:
                    folded = self._fold_instr(instr)
                    if isinstance(folded, list):
                        new_instrs.extend(folded)
                    elif folded is not None:
                        new_instrs.append(folded)
                    # None means delete (unreachable after fold)
                bb.instructions = new_instrs

    def _fold_instr(self, instr) -> Any:
        """Try to constant-fold a single instruction. Returns modified instr or None."""
        if isinstance(instr, IRBinary):
            if instr.left.kind == 'const' and instr.right.kind == 'const':
                try:
                    a = instr.left.const_value
                    b = instr.right.const_value
                    op = instr.op
                    result = self._eval_binary(op, a, b)
                    if result is not None:
                        # Replace with copy from constant
                        ctype = instr.dest.ctype or 'int'
                        return IRCopy(_cv(result, ctype), instr.dest)
                except (TypeError, ValueError, ZeroDivisionError):
                    pass

        elif isinstance(instr, IRUnary):
            if instr.operand.kind == 'const':
                try:
                    val = instr.operand.const_value
                    if instr.op == '-':
                        return IRCopy(_cv(-val, instr.dest.ctype), instr.dest)
                    elif instr.op == '!':
                        return IRCopy(_cv(1 if not val else 0, 'bool'), instr.dest)
                    elif instr.op == '~':
                        return IRCopy(_cv(~int(val), instr.dest.ctype), instr.dest)
                except (TypeError, ValueError):
                    pass

        elif isinstance(instr, IRCast):
            if instr.src.kind == 'const':
                try:
                    val = instr.src.const_value
                    return IRCopy(_cv(val, instr.target_type), instr.dest)
                except (TypeError, ValueError):
                    pass

        elif isinstance(instr, IRBranch):
            cond = instr.cond
            if isinstance(cond, IRValue) and cond.kind == 'const':
                val = cond.const_value
                if val:
                    return IRJump(instr.true_label)
                else:
                    return IRJump(instr.false_label)

        return instr

    def _eval_binary(self, op: str, a: Any, b: Any) -> Any:
        """Evaluate a binary operation with constant operands."""
        try:
            if op == '+':   return a + b
            if op == '-':   return a - b
            if op == '*':   return a * b
            if op == '/':
                if b == 0:
                    return None
                return a / b if isinstance(a, float) or isinstance(b, float) else a // b
            if op == '%':   return a % b if b != 0 else None
            if op == '==':  return 1 if a == b else 0
            if op == '!=':  return 1 if a != b else 0
            if op == '<':   return 1 if a < b else 0
            if op == '>':   return 1 if a > b else 0
            if op == '<=':  return 1 if a <= b else 0
            if op == '>=':  return 1 if a >= b else 0
            if op == '&&':  return 1 if a and b else 0
            if op == '||':  return 1 if a or b else 0
            if op == '&':   return int(a) & int(b)
            if op == '|':   return int(a) | int(b)
            if op == '^':   return int(a) ^ int(b)
            if op == '<<':  return int(a) << int(b)
            if op == '>>':  return int(a) >> int(b)
        except (TypeError, ValueError, ZeroDivisionError):
            return None
        return None

    # ─────────────────────────────────────────
    #  PASS 2: DEAD CODE ELIMINATION
    # ─────────────────────────────────────────

    def dead_code_elimination(self) -> None:
        """
        Remove unreachable basic blocks and unused functions.
        A block is reachable if it can be reached from the entry block.
        """
        for fn in self.module.functions:
            fn.blocks = self._remove_unreachable_blocks(fn)

        # Remove functions with empty bodies (no effective code)
        self.module.functions = [
            fn for fn in self.module.functions
            if self._has_effect(fn)
        ]

    def _remove_unreachable_blocks(self, fn: IRFunction) -> List[BasicBlock]:
        """Remove blocks not reachable from the entry."""
        if not fn.blocks:
            return []

        # Build successor map
        successors: Dict[str, List[str]] = {}
        for bb in fn.blocks:
            successors[bb.label] = []
            term = bb.terminator
            if isinstance(term, IRJump):
                successors[bb.label].append(term.label)
            elif isinstance(term, IRBranch):
                successors[bb.label].extend([term.true_label, term.false_label])
            elif isinstance(term, IRReturn):
                pass  # no successors
            else:
                # Fall-through to next block
                idx = fn.blocks.index(bb)
                if idx + 1 < len(fn.blocks):
                    successors[bb.label].append(fn.blocks[idx + 1].label)

        # DFS from entry
        entry_label = fn.entry_block or (fn.blocks[0].label if fn.blocks else '')
        reachable: set = set()
        stack = [entry_label]
        while stack:
            label = stack.pop()
            if label in reachable:
                continue
            reachable.add(label)
            for succ in successors.get(label, []):
                if succ not in reachable:
                    stack.append(succ)

        # Keep only reachable blocks
        # Also keep blocks that may be targets but unreachable (remove them anyway)
        result = [bb for bb in fn.blocks if bb.label in reachable]

        # Fix up branch targets that point to removed blocks
        # (replace with jump to next reachable, or return)
        # For now, just eliminate — if a branch points to removed block,
        # the branch becomes unreachable too
        return result

    def _has_effect(self, fn: IRFunction) -> bool:
        """Check if a function has any effect (non-trivial instructions)."""
        for bb in fn.blocks:
            for instr in bb.instructions:
                if isinstance(instr, (IRLabel, IRLabel)):
                    continue
                if isinstance(instr, IRReturn) and instr.value is None:
                    # Bare void return doesn't count
                    continue
                return True
        return False

    # ─────────────────────────────────────────
    #  PASS 3: EMPTY HANDLER REMOVAL
    # ─────────────────────────────────────────

    def empty_handler_removal(self) -> None:
        """
        Remove every/on handlers that have empty bodies.
        This is a semantic pass — handlers with no user code are deleted.
        """
        self.module.every_handlers = [
            h for h in self.module.every_handlers
            if h.get('has_body', True)
        ]
        self.module.on_event_handlers = [
            h for h in self.module.on_event_handlers
            if h.get('has_body', True)
        ]
        self.module.on_threshold_handlers = [
            h for h in self.module.on_threshold_handlers
            if h.get('has_body', True)
        ]

        # Also remove the corresponding functions
        handler_names: set = set()
        for h_list in [self.module.every_handlers,
                        self.module.on_event_handlers,
                        self.module.on_threshold_handlers]:
            for h in h_list:
                handler_names.add(h.get('name', ''))

        self.module.functions = [
            fn for fn in self.module.functions
            if fn.name not in handler_names
            or fn.name in handler_names  # Keep if still referenced (it's a set)
        ]

    # ─────────────────────────────────────────
    #  PASS 4: REDUNDANT STORE ELIMINATION
    # ─────────────────────────────────────────

    def redundant_store_elimination(self) -> None:
        """
        Remove stores to variables that are never subsequently read.
        Example: x = 5; x = 10;  →  x = 10;  (first store is dead)
        """
        for fn in self.module.functions:
            for bb in fn.blocks:
                self._rse_block(bb)

    def _rse_block(self, bb: BasicBlock) -> None:
        """Eliminate redundant stores within a single basic block."""
        # Map: variable name → index in instructions
        last_store: Dict[str, int] = {}
        to_remove: set = set()

        for i, instr in enumerate(bb.instructions):
            if isinstance(instr, IRCopy):
                if instr.dest.kind == 'var':
                    name = instr.dest.name
                    if name in last_store:
                        # Previous store to same variable is dead
                        to_remove.add(last_store[name])
                    last_store[name] = i
            elif isinstance(instr, IRBinary) and instr.dest.kind == 'var':
                name = instr.dest.name
                # Binary ops read the dest, so it's not a simple overwrite
                # But if the previous store is never read between then and now...
                # For simplicity, just track pure copies
                pass
            elif isinstance(instr, IRStore):
                name = instr.dest.name
                if name in last_store:
                    to_remove.add(last_store[name])
                last_store[name] = i

            # Any instruction that reads a variable invalidates its last store
            for used_val in self._used_vars(instr):
                last_store.pop(used_val, None)

        bb.instructions = [
            instr for i, instr in enumerate(bb.instructions)
            if i not in to_remove
        ]

    def _used_vars(self, instr) -> set:
        """Return the set of variable names read by an instruction."""
        names: set = set()
        if isinstance(instr, IRBinary):
            for v in [instr.left, instr.right]:
                if v.kind == 'var':
                    names.add(v.name)
        elif isinstance(instr, IRUnary):
            if instr.operand.kind == 'var':
                names.add(instr.operand.name)
        elif isinstance(instr, IRCopy):
            if instr.src.kind == 'var':
                names.add(instr.src.name)
        elif isinstance(instr, IRLoad):
            if instr.src.kind == 'var':
                names.add(instr.src.name)
        elif isinstance(instr, IRStore):
            if instr.src.kind == 'var':
                names.add(instr.src.name)
        elif isinstance(instr, IRBranch):
            if isinstance(instr.cond, IRValue) and instr.cond.kind == 'var':
                names.add(instr.cond.name)
        elif isinstance(instr, IRReturn):
            if instr.value and instr.value.kind == 'var':
                names.add(instr.value.name)
        elif isinstance(instr, IRCall):
            for arg in instr.args:
                if arg.kind == 'var':
                    names.add(arg.name)
        elif isinstance(instr, IRCallIndirect):
            for arg in instr.args:
                if arg.kind == 'var':
                    names.add(arg.name)
        elif isinstance(instr, IRCast):
            if instr.src.kind == 'var':
                names.add(instr.src.name)
        elif isinstance(instr, IRMemberAccess):
            if instr.obj.kind == 'var':
                names.add(instr.obj.name)
        elif isinstance(instr, IRArrayAccess):
            if instr.base.kind == 'var':
                names.add(instr.base.name)
            if instr.index.kind == 'var':
                names.add(instr.index.name)
        return names

    # ─────────────────────────────────────────
    #  PASS 2.5: COPY PROPAGATION
    # ─────────────────────────────────────────

    def copy_propagation(self) -> None:
        """
        Forward-substitute simple copies within each basic block.
        t1 = x;  ... = t1 + y;  →  ... = x + y;
        Then the dead copy can be removed by dead_temp_elimination.
        """
        for fn in self.module.functions:
            for bb in fn.blocks:
                self._cp_block(bb)

    def _cp_block(self, bb: BasicBlock) -> None:
        """Apply copy propagation within a single basic block."""
        # Map: temp_name → IRValue to substitute
        copies: Dict[str, IRValue] = {}
        new_instrs = []
        for instr in bb.instructions:
            # Substitute uses of known copies
            self._cp_replace_uses(instr, copies)

            # Record new copy definitions
            if isinstance(instr, IRCopy):
                if instr.dest.kind == 'temp' and instr.src.kind in ('var', 'global', 'const', 'temp', 'param'):
                    copies[instr.dest.name] = instr.src

            new_instrs.append(instr)
        bb.instructions = new_instrs

    def _cp_replace_uses(self, instr, copies: Dict[str, IRValue]) -> None:
        """Replace uses of copied temps with their source values."""
        fields_to_check = ['src', 'left', 'right', 'operand', 'base', 'index', 'obj']
        for fname in fields_to_check:
            val = getattr(instr, fname, None)
            if val and isinstance(val, IRValue) and val.kind == 'temp':
                if val.name in copies:
                    setattr(instr, fname, copies[val.name])
        # Also check args list for IRCall/IRCallIndirect
        if hasattr(instr, 'args'):
            new_args = []
            for arg in instr.args:
                if arg.kind == 'temp' and arg.name in copies:
                    new_args.append(copies[arg.name])
                else:
                    new_args.append(arg)
            instr.args = new_args

    # ─────────────────────────────────────────
    #  PASS 2.8: DEAD TEMP ELIMINATION
    # ─────────────────────────────────────────

    def dead_temp_elimination(self) -> None:
        """
        Remove instructions whose destination temp is never used.
        Collects all temp uses across the function, then removes unused defs.
        """
        for fn in self.module.functions:
            self._dte_function(fn)

    def _dte_function(self, fn: IRFunction) -> None:
        """Eliminate dead temp definitions within a function."""
        # Collect: which temps are defined, which are used
        defined: Dict[str, int] = {}  # name → definition count
        used: set = set()

        for bb in fn.blocks:
            for instr in bb.instructions:
                if isinstance(instr, (IRBinary, IRUnary, IRCall, IRCallIndirect,
                                      IRCast, IRArrayAccess, IRMemberAccess,
                                      IRCopy, IRLoad)):
                    if instr.dest and instr.dest.kind == 'temp':
                        defined[instr.dest.name] = defined.get(instr.dest.name, 0) + 1
                # Collect all temp uses
                for used_name in self._temp_uses(instr):
                    used.add(used_name)

        # Temps defined but never used (after accounting for multiple defs)
        dead = set()
        for name, count in defined.items():
            if name not in used:
                dead.add(name)

        if not dead:
            return

        # Remove instructions that define only dead temps
        for bb in fn.blocks:
            bb.instructions = [
                instr for instr in bb.instructions
                if not self._is_dead_def(instr, dead)
            ]

    def _is_dead_def(self, instr, dead: set) -> bool:
        """Check if an instruction defines a dead temp and has no side effects."""
        dest = getattr(instr, 'dest', None)
        if not dest or dest.kind != 'temp':
            return False
        if dest.name not in dead:
            return False
        # Don't remove function calls (side effects) even if temp is unused
        if isinstance(instr, (IRCall, IRCallIndirect)):
            return False  # Keep the call for side effects even if result unused
        if isinstance(instr, IRStore):
            return False  # Stores have side effects
        return True

    def _temp_uses(self, instr) -> set:
        """Return set of temp names used by an instruction."""
        names: set = set()
        fields = ['src', 'left', 'right', 'operand', 'base', 'index', 'obj',
                  'cond', 'value']
        for fname in fields:
            val = getattr(instr, fname, None)
            if val and isinstance(val, IRValue) and val.kind == 'temp':
                names.add(val.name)
        if hasattr(instr, 'args'):
            for arg in instr.args:
                if arg.kind == 'temp':
                    names.add(arg.name)
        return names

    # ─────────────────────────────────────────
    #  PASS 5: STACK PROMOTION
    # ─────────────────────────────────────────

    def stack_promotion(self) -> None:
        """
        Move function-local variables from global scope to stack (function locals).

        Variables declared at global scope but only used within a single function
        are promoted to locals within that function.
        """
        # Build: global name → set of functions that reference it
        global_usage: Dict[str, set] = {}
        for g in self.module.globals:
            if g.is_const or g.is_pin:
                continue  # Don't demote constants or pin defs
            global_usage[g.name] = set()

        # Scheduler/event globals are special — skip those
        special_prefixes = ('_iotift_', 'user_loop')

        for fn in self.module.functions:
            for bb in fn.blocks:
                for instr in bb.instructions:
                    vars_used = self._all_refs(instr)
                    for v in vars_used:
                        if v in global_usage:
                            global_usage[v].add(fn.name)

        # Promote globals that are only used in one function
        promoted: set = set()
        for name, fns in global_usage.items():
            if len(fns) == 1 and name in global_usage:
                # Check it's not a special name
                if not any(name.startswith(p) for p in special_prefixes):
                    promoted.add(name)

        # Move from globals to function locals
        promoted_globals = {g.name: g for g in self.module.globals if g.name in promoted}

        self.module.globals = [
            g for g in self.module.globals
            if g.name not in promoted
        ]

        for fn in self.module.functions:
            fn.locals.extend([
                IRValue('var', name, g.ctype)
                for name, g in promoted_globals.items()
                if fn.name in global_usage.get(name, set())
            ])

    def _all_refs(self, instr) -> set:
        """Return all value references (both var and global kind) in an instruction."""
        names: set = set()
        fields = {
            IRBinary: ['left', 'right'],
            IRUnary: ['operand'],
            IRCopy: ['src', 'dest'],
            IRLoad: ['src', 'dest'],
            IRStore: ['src', 'dest'],
            IRBranch: ['cond'],
            IRReturn: ['value'],
            IRCall: ['args', 'dest'],
            IRCallIndirect: ['args', 'dest'],
            IRCast: ['src', 'dest'],
            IRMemberAccess: ['obj', 'dest'],
            IRArrayAccess: ['base', 'index', 'dest'],
        }
        instr_fields = fields.get(type(instr), [])
        for fname in instr_fields:
            val = getattr(instr, fname, None)
            if isinstance(val, IRValue) and val.kind in ('var', 'global'):
                names.add(val.name)
            elif isinstance(val, list):
                for v in val:
                    if isinstance(v, IRValue) and v.kind in ('var', 'global'):
                        names.add(v.name)
        return names
