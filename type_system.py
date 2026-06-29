"""
IOTIFT Type System

Fixed-width types, enums, compound types, type checking.
Replaces the old 4-entry dict in codegen.py with a proper type system.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple
from enum import Enum as PyEnum


# ─────────────────────────────────────────
#  TYPE KINDS
# ─────────────────────────────────────────

class TypeKind(PyEnum):
    """Fundamental type categories."""
    VOID    = 'void'
    BOOL    = 'bool'
    INT     = 'int'        # platform-width signed
    UINT    = 'uint'       # platform-width unsigned
    FLOAT   = 'float'      # platform-width float
    STR     = 'str'
    CHAR    = 'char'
    FIXED_INT  = 'fixed_int'   # i8, i16, i32, i64
    FIXED_UINT = 'fixed_uint'  # u8, u16, u32, u64
    FIXED_FLOAT = 'fixed_float' # f32, f64
    ARRAY   = 'array'
    STRUCT  = 'struct'
    ENUM    = 'enum'
    FN      = 'fn'


# ─────────────────────────────────────────
#  TYPE REPRESENTATION
# ─────────────────────────────────────────

@dataclass
class Type:
    """Base type. All Iotift types derive from this."""
    kind: TypeKind
    name: str = ""                  # user-visible name
    size_bytes: int = 0             # sizeof in bytes
    alignment: int = 0              # alignment requirement
    is_signed: bool = False
    is_const: bool = False
    is_volatile: bool = False

    def with_const(self) -> 'Type':
        t = Type(kind=self.kind, name=f'const {self.name}',
                 size_bytes=self.size_bytes, alignment=self.alignment,
                 is_signed=self.is_signed, is_const=True, is_volatile=self.is_volatile)
        t.__dict__.update({k: v for k, v in self.__dict__.items()
                           if k not in ('kind', 'name', 'is_const')})
        return t

    def with_volatile(self) -> 'Type':
        t = Type(kind=self.kind, name=f'volatile {self.name}',
                 size_bytes=self.size_bytes, alignment=self.alignment,
                 is_signed=self.is_signed, is_const=self.is_const, is_volatile=True)
        t.__dict__.update({k: v for k, v in self.__dict__.items()
                           if k not in ('kind', 'name', 'is_volatile')})
        return t

    def c_type(self) -> str:
        """Return C type string for this type."""
        return self.name

    def __repr__(self) -> str:
        return f"Type({self.name})"


class VoidType(Type):
    def __init__(self):
        super().__init__(kind=TypeKind.VOID, name='void', size_bytes=0)

    def c_type(self) -> str:
        return 'void'


class BoolType(Type):
    def __init__(self):
        super().__init__(kind=TypeKind.BOOL, name='bool', size_bytes=1,
                         alignment=1)

    def c_type(self) -> str:
        return 'bool'


class IntType(Type):
    def __init__(self):
        super().__init__(kind=TypeKind.INT, name='int', size_bytes=4,
                         alignment=4, is_signed=True)

    def c_type(self) -> str:
        return 'int'


class UIntType(Type):
    def __init__(self):
        super().__init__(kind=TypeKind.UINT, name='uint', size_bytes=4,
                         alignment=4)

    def c_type(self) -> str:
        return 'unsigned int'


class FloatType(Type):
    def __init__(self):
        super().__init__(kind=TypeKind.FLOAT, name='float', size_bytes=4,
                         alignment=4, is_signed=True)

    def c_type(self) -> str:
        return 'float'


class StrType(Type):
    def __init__(self):
        super().__init__(kind=TypeKind.STR, name='str', size_bytes=4,
                         alignment=4)

    def c_type(self) -> str:
        return 'const char*'


class CharType(Type):
    def __init__(self):
        super().__init__(kind=TypeKind.CHAR, name='char', size_bytes=1,
                         alignment=1)

    def c_type(self) -> str:
        return 'char'


class FixedIntType(Type):
    """Fixed-width signed integer: i8, i16, i32, i64."""
    def __init__(self, bits: int):
        name = f'i{bits}'
        super().__init__(kind=TypeKind.FIXED_INT, name=name,
                         size_bytes=bits // 8, alignment=bits // 8,
                         is_signed=True)
        self.bits = bits

    def c_type(self) -> str:
        return f'int{self.bits}_t'


class FixedUIntType(Type):
    """Fixed-width unsigned integer: u8, u16, u32, u64."""
    def __init__(self, bits: int):
        name = f'u{bits}'
        super().__init__(kind=TypeKind.FIXED_UINT, name=name,
                         size_bytes=bits // 8, alignment=bits // 8)
        self.bits = bits

    def c_type(self) -> str:
        return f'uint{self.bits}_t'


class FixedFloatType(Type):
    """Fixed-width float: f32, f64."""
    def __init__(self, bits: int):
        name = f'f{bits}'
        super().__init__(kind=TypeKind.FIXED_FLOAT, name=name,
                         size_bytes=bits // 8, alignment=bits // 8,
                         is_signed=True)
        self.bits = bits

    def c_type(self) -> str:
        return 'float' if self.bits == 32 else 'double'


class ArrayType(Type):
    """Fixed-size array: [N]T."""
    def __init__(self, elem_type: Type, size: int):
        name = f'{elem_type.name}[{size}]'
        super().__init__(kind=TypeKind.ARRAY, name=name,
                         size_bytes=elem_type.size_bytes * size,
                         alignment=elem_type.alignment)
        self.elem_type = elem_type
        self.array_size = size

    def c_type(self) -> str:
        return f'{self.elem_type.c_type()}[{self.array_size}]'


class StructType(Type):
    """User-defined struct."""
    def __init__(self, name: str, fields: List[Tuple[str, Type]]):
        total_size = sum(f[1].size_bytes for f in fields)
        max_align = max((f[1].alignment for f in fields), default=1)
        super().__init__(kind=TypeKind.STRUCT, name=name,
                         size_bytes=total_size, alignment=max_align)
        self.fields = fields  # list of (field_name, Type)

    def field_type(self, name: str) -> Optional[Type]:
        for fname, ftype in self.fields:
            if fname == name:
                return ftype
        return None

    def c_type(self) -> str:
        return self.name


class EnumType(Type):
    """User-defined enum."""
    def __init__(self, name: str, variants: List[Tuple[str, int]],
                 backing_type: Type = None):
        bt = backing_type or IntType()
        super().__init__(kind=TypeKind.ENUM, name=name,
                         size_bytes=bt.size_bytes, alignment=bt.alignment)
        self.variants = variants       # [(name, discriminant), ...]
        self.backing_type = bt

    def variant_value(self, name: str) -> Optional[int]:
        for vname, val in self.variants:
            if vname == name:
                return val
        return None

    def c_type(self) -> str:
        return self.name


class FnType(Type):
    """Function type: (params...) -> return_type."""
    def __init__(self, param_types: List[Type], return_type: Type):
        name = f'fn({",".join(p.name for p in param_types)}) -> {return_type.name}'
        super().__init__(kind=TypeKind.FN, name=name, size_bytes=0)
        self.param_types = param_types
        self.return_type = return_type


# ─────────────────────────────────────────
#  TYPE PRIMITIVES (singleton instances)
# ─────────────────────────────────────────

VOID  = VoidType()
BOOL  = BoolType()
INT   = IntType()
UINT  = UIntType()
FLOAT = FloatType()
STR   = StrType()
CHAR  = CharType()

I8  = FixedIntType(8)
I16 = FixedIntType(16)
I32 = FixedIntType(32)
I64 = FixedIntType(64)
U8  = FixedUIntType(8)
U16 = FixedUIntType(16)
U32 = FixedUIntType(32)
U64 = FixedUIntType(64)
F32 = FixedFloatType(32)
F64 = FixedFloatType(64)


# ─────────────────────────────────────────
#  TYPE NAME → TYPE RESOLUTION
# ─────────────────────────────────────────

_BUILTIN_TYPES: Dict[str, Type] = {
    'void':  VOID,
    'bool':  BOOL,
    'int':   INT,
    'uint':  UINT,
    'float': FLOAT,
    'str':   STR,
    'char':  CHAR,
    'i8':    I8,   'i16': I16, 'i32': I32, 'i64': I64,
    'u8':    U8,   'u16': U16, 'u32': U32, 'u64': U64,
    'f32':   F32,  'f64':  F64,
}


def resolve_builtin_type(name: str) -> Optional[Type]:
    """Look up a built-in type by name. Returns None if not found."""
    return _BUILTIN_TYPES.get(name)


def is_builtin_type(name: str) -> bool:
    """Check if a name refers to a built-in type."""
    return name in _BUILTIN_TYPES


def is_integer_type(t: Type) -> bool:
    """True if t is any integer type (signed or unsigned)."""
    return t.kind in (TypeKind.INT, TypeKind.UINT,
                       TypeKind.FIXED_INT, TypeKind.FIXED_UINT,
                       TypeKind.BOOL, TypeKind.CHAR)


def is_numeric_type(t: Type) -> bool:
    """True if t is any numeric type."""
    return is_integer_type(t) or t.kind in (TypeKind.FLOAT, TypeKind.FIXED_FLOAT)


def is_signed_type(t: Type) -> bool:
    """True if t is a signed numeric type."""
    return getattr(t, 'is_signed', False)


def common_type(a: Type, b: Type) -> Optional[Type]:
    """Find a common type that both a and b can convert to. Used for binops."""
    if a.kind == b.kind and a.name == b.name:
        return a
    # Both numeric → promote to wider type
    if is_numeric_type(a) and is_numeric_type(b):
        if a.kind in (TypeKind.FIXED_FLOAT, TypeKind.FLOAT) or \
           b.kind in (TypeKind.FIXED_FLOAT, TypeKind.FLOAT):
            if a.size_bytes >= b.size_bytes:
                return a
            return b
        # Integer promotion
        if a.size_bytes >= b.size_bytes:
            return a
        return b
    return None


def can_assign(target_type: Type, value_type: Type) -> bool:
    """Check if value_type can be assigned to a slot of target_type."""
    if target_type.name == value_type.name:
        return True
    if target_type.kind == TypeKind.FLOAT and is_integer_type(value_type):
        return True  # int → float implicit
    if is_integer_type(target_type) and is_integer_type(value_type):
        return target_type.size_bytes >= value_type.size_bytes  # widening only
    return False
