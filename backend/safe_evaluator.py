import ast
import operator


allowed_operators = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}


class SafeEvaluator(ast.NodeVisitor):
    """
    A safe evaluator for raster math expressions using AST.
    """

    def __init__(self, context):
        self.context = context  # dict of variable names → Raster objects

    def evaluate(self, expr):
        """Evaluate the expression using context variables."""
        tree = ast.parse(expr, mode="eval")
        return self.visit(tree.body)

    def visit_BinOp(self, node):
        left = self.visit(node.left)
        right = self.visit(node.right)
        op_type = type(node.op)
        if op_type in allowed_operators:
            return allowed_operators[op_type](left, right)
        raise ValueError(f"Operator {op_type} not allowed")

    def visit_UnaryOp(self, node):
        operand = self.visit(node.operand)
        if isinstance(node.op, ast.USub):
            return -operand
        raise ValueError("Unsupported unary operator")

    def visit_Name(self, node):
        if node.id in self.context:
            return self.context[node.id]
        raise NameError(f"Variable '{node.id}' not found")

    def visit_Constant(self, node):
        return node.value

    def generic_visit(self, node):
        raise ValueError(f"Unsupported expression: {ast.dump(node)}")
