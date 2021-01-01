from typing import Dict, Sequence, List, NoReturn
from tools.codegen.api.types import *

# This file implements a small program synthesis engine that implements
# conversions between one API to another.
#
# The key data type in this file in CType, short for C++ semantic type.  A CType
# represents a C++ type, plus semantic information about what it represents.
# For example, consider the argument "bool pin_memory"; its normal C++ type is
# "bool", but its C++ semantic type also keeps track that this represents a
# "pin_memory"; you can't just use a random other boolean in a context where you
# need a "pin_memory"!
#
# The translator takes a list of needed CTypes, and then figures out how
# to construct expressions with these CTypes from the given bindings.  Many
# of these expressions are trivial (I need a Tensor other; there's a Tensor
# other scope); others are more nontrivial and may require packing/unpacking.
# Some examples of non-trivial action:
#
#   - Need the "dtype" binding?  Well, maybe "dtype" isn't available
#     in the context, instead, "options" is, and you need to extract
#     it from there.  (Gather)
#
#   - Need the "context" binding?  Well, maybe "context" isn't available
#     in the context, and you need to construct it from "dtype", "device",
#     etc.  (Scatter)
#
#   - Need the "memory_format" binding?  Well, actually, it's available
#     from both "memory_format" and "options", so you had better make sure
#     they are consistent.  (Join)

options_ctype = ConstRefCType(BaseCType("TensorOptions", "options"))

class UnsatError(RuntimeError):
    pass

# Given a set of in-scope bindings and a set of target bindings, synthesize
# a list of expressions that uses only the in-scope bindings (bindings) that
# have all of the types of goals.  You may want to use this function if
# you're generating code for a function like:
#
#   void f({args}) {
#     g({exprs}); // g is a different API
#   }
#
# and you need to generate "exprs".
#
# TODO: Don't need full Binding for goals, CType will do
# TODO: Don't need full Binding for bindings, list of Expr will do
def translate(bindings: Sequence[Binding], goals: Sequence[Binding], *, method: bool = False) -> List[Expr]:
    # Add all the bindings to the context
    ctx: Dict[CType, str] = {}
    for b in bindings:
        ctx[b.ctype] = b.name

    # Add implicit bindings if the generated code is inside a Tensor method
    if method:
        ctx[MutRefCType(BaseCType("Tensor", "self"))] = "const_cast<Tensor&>(*this)"
        ctx[ConstRefCType(BaseCType("Tensor", "self"))] = "const_cast<Tensor&>(*this)"
        # This is better!  Byte-for-byte compat
        # ctx[ConstRefCType(BaseCType("Tensor", "self"))] = "*this"

    def unsat(goal: CType) -> NoReturn:
        ctx_desc = '\n'.join(f"  {t.cpp_type()} {e};" for t, e in ctx.items())
        raise UnsatError(f'''
Failed to synthesize the expression "{goal.cpp_type()} {goal.name}"
while trying to translate from:

  from_func({', '.join(b.defn() for b in bindings)})

to:

  to_func({', '.join(g.defn() for g in goals)})

When I failed, the following bindings were available in the context:

{ctx_desc}

This probably means there is a missing rule in the rules of tools.codegen.api.translate.
Check this module for more information.
''')

    # A shitty backtracking search implementation.  It's shitty because it
    # doesn't actually do backtracing or search. In particular, if
    # direct=True, we won't try to do any fancy synthesis, just trivial
    # conversions (e.g., "T a" is OK for "const T& a").  So all of the
    # existing rules in this function simply try to solve immediately,
    # and bail if things don't work out.
    def solve(goal: CType, *, direct: bool) -> str:
        def direct_solve(goal: CType) -> str:
            return solve(goal, direct=True)

        if goal in ctx:
            # Trivial
            return ctx[goal]

        # If the goal is a const&, try solving for the value type first
        if isinstance(goal, ConstRefCType):
            try:
                return solve(goal.elem, direct=direct)
            except UnsatError:
                pass

        if direct:
            unsat(goal)

        # For now, all of these rules are mutually exclusive.
        if goal == OptionalCType(BaseCType("MemoryFormat", "memory_format")):
            memory_format = direct_solve(
                OptionalCType(BaseCType("MemoryFormat", SpecialArgName.possibly_redundant_memory_format))
            )
            try:
                options = direct_solve(options_ctype)
                return f"c10::impl::check_tensor_options_and_extract_memory_format({options}, {memory_format})"
            except UnsatError:
                return memory_format

        elif goal == BaseCType("TensorOptions", "options"):
            dtype = direct_solve(OptionalCType(BaseCType("ScalarType", "dtype")))
            pin_memory = direct_solve(OptionalCType(BaseCType("bool", "pin_memory")))
            device = direct_solve(OptionalCType(BaseCType("Device", "device")))
            layout = direct_solve(OptionalCType(BaseCType("Layout", "layout")))
            return f'TensorOptions().dtype({dtype}).layout({layout}).device({device}).pinned_memory({pin_memory})'

        elif goal == OptionalCType(BaseCType("ScalarType", "dtype")):
            options = direct_solve(options_ctype)
            return f'optTypeMetaToScalarType({options}.dtype_opt())'

        elif goal == OptionalCType(BaseCType("Layout", "layout")):
            options = direct_solve(options_ctype)
            return f'{options}.layout_opt()'

        elif goal == OptionalCType(BaseCType("Device", "device")):
            options = direct_solve(options_ctype)
            return f'{options}.device_opt()'

        elif goal == OptionalCType(BaseCType("bool", "pin_memory")):
            options = direct_solve(options_ctype)
            return f'{options}.pinned_memory_opt()'

        unsat(goal)

    return [Expr(solve(g.ctype, direct=False), g.ctype) for g in goals]
