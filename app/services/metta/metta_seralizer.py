from hyperon import SymbolAtom, ExpressionAtom, GroundedAtom

def recurssive_seralize(metta_expression, result):
    for node in metta_expression:
        if isinstance(node, SymbolAtom):
            result.append(node.get_name())
        elif isinstance(node, GroundedAtom):
            result.append(str(node))
        elif isinstance(node, ExpressionAtom):
            recurssive_seralize(node.get_children(), result)
    return result

def metta_seralizer(metta_result):
    result = []

    if len(metta_result) == 0:
        return []

    for node in metta_result:
        # Check if node has get_children (ExpressionAtom)
        if not hasattr(node, "get_children"):
            continue
        node_children = node.get_children()
        for metta_symbol in node_children:
            if isinstance(metta_symbol, SymbolAtom) and metta_symbol.get_name() == ",":
                continue
            elif isinstance(metta_symbol, ExpressionAtom):
                res = recurssive_seralize(metta_symbol.get_children(), [])
                result.append(tuple(res))
    return result
