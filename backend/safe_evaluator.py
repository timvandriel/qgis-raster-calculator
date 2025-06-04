import ast
import operator

# Operators allowed in the safe evaluation
allowed_operators = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}


class SafeEvaluator(ast.NodeVisitor):
    """
    A safe evaluator for mathematical expressions using AST.
    This class only allows a limited set of operations and variable names
    defined in the provided context.
    It raises exceptions for unsupported operations or variables.
    """

    def __init__(self, context):
        self.context = (
            context  # Context should be a dictionary of variable names and their values
        )

    def visit_BinOp(self, node):
        """
        Visit a binary operation node and evaluate it safely.
        Only allows specific operators defined in allowed_operators.
        """
        left = self.visit(node.left)  # Recursively visit the left operand
        right = self.visit(node.right)  # Recursively visit the right operand
        op_type = type(node.op)  # Get the type of the operator
        if op_type in allowed_operators:
            return allowed_operators[op_type](left, right)
        raise ValueError(f"Operator {op_type} not allowed")

    def visit_Name(self, node):
        """
        Visit a variable name node and return its value from the context.
        Raises NameError if the variable is not found in the context.
        """
        if node.id in self.context:
            return self.context[node.id]
        raise NameError(f"Variable '{node.id}' not found")

    def visit_Constant(self, node):
        """
        Visit a constant value node and return its value.
        Handles numeric constants (int, float) and strings.
        """
        return node.value

    def visit_UnaryOp(self, node):
        """
        Visit a unary operation node (like negation) and evaluate it safely.
        Only allows unary subtraction (negation)."""
        operand = self.visit(node.operand)
        if isinstance(node.op, ast.USub):
            return -operand
        raise ValueError("Unsupported unary operator")

    def generic_visit(self, node):
        """
        Generic visit method for unsupported nodes.
        Raises ValueError for any unsupported expression types.
        """
        raise ValueError(f"Unsupported expression: {ast.dump(node)}")
