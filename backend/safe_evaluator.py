import ast
import operator


allowed_binops = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.BitAnd: operator.and_,
    ast.BitOr: operator.or_,
}

allowed_unaryops = {
    ast.USub: operator.neg,  # -x
    ast.Invert: operator.invert,  # ~x (bitwise NOT)
}

allowed_cmpops = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}


class SafeEvaluator(ast.NodeVisitor):
    """
    A safe evaluator for raster math expressions using AST.
    """

    def __init__(self, context):
        self.context = context  # dict of variable names → Raster objects

    def evaluate(self, expr):
        tree = ast.parse(expr, mode="eval")
        return self.visit(tree.body)

    def visit_BinOp(self, node):
        left = self.visit(node.left)
        right = self.visit(node.right)
        op_type = type(node.op)
        if op_type in allowed_binops:
            return allowed_binops[op_type](left, right)
        raise ValueError(f"Binary operator {op_type} not allowed")

    def visit_UnaryOp(self, node):
        operand = self.visit(node.operand)
        op_type = type(node.op)
        if op_type in allowed_unaryops:
            return allowed_unaryops[op_type](operand)
        raise ValueError(f"Unary operator {op_type} not allowed")

    def visit_Compare(self, node):
        if len(node.ops) != 1 or len(node.comparators) != 1:
            raise ValueError("Only simple comparisons are supported")
        left = self.visit(node.left)
        right = self.visit(node.comparators[0])
        op_type = type(node.ops[0])
        if op_type in allowed_cmpops:
            return allowed_cmpops[op_type](left, right)
        raise ValueError(f"Comparison operator {op_type} not allowed")

    def visit_Name(self, node):
        if node.id in self.context:
            return self.context[node.id]
        raise NameError(f"Variable '{node.id}' not found")

    def visit_Constant(self, node):
        return node.value

    def generic_visit(self, node):
        raise ValueError(f"Unsupported expression: {ast.dump(node)}")
