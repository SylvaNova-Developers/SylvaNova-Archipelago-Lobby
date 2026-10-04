"""Compatibility shims for Archipelago rule_builder when hosting third-party apworlds.

Some community apworlds (notably tww3 0.11.0) pass float item counts into Has/HasGroup
rules via Python 3 true division, e.g. ``len(items) * min(1, (index // 6) / 8)``.
rule_builder's ``resolve_field(..., int)`` then raises:

    AssertionError: Expected type <class 'int'> but got <class 'float'>

Item counts are inherently integral, so truncating toward zero is the right host-side
behavior and unblocks YAML validation / generation for those worlds.
"""


def patch_rule_builder_int_coercion():
    try:
        from rule_builder import field_resolvers
        from rule_builder import rules as rule_builder_rules
    except ImportError:
        return False

    current = field_resolvers.resolve_field
    if getattr(current, "_aplobby_float_int_patch", False):
        return True

    def resolve_field(field, world, expected_type=None):
        if isinstance(field, field_resolvers.FieldResolver):
            field = field.resolve(world)
        if expected_type is int and isinstance(field, float):
            field = int(field)
        if expected_type:
            assert isinstance(field, expected_type), (
                f"Expected type {expected_type} but got {type(field)}"
            )
        return field

    resolve_field._aplobby_float_int_patch = True
    field_resolvers.resolve_field = resolve_field
    rule_builder_rules.resolve_field = resolve_field
    return True
