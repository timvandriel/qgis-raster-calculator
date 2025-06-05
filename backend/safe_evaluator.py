import ast
import operator
import numpy as np

# Allowed operators for the expression evaluator
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
    It supports limited operations and calculates a safe output dtype.
    """

    def __init__(self, context):
        self.context = context  # dict of variable names → Raster objects
        self.variables = set()  # to track variable names used in the expression
        self.operations = set()  # to track operations used in the expression

    def evaluate(self, expr):
        """
        Evaluate a mathematical expression string using the context variables.
        The expression should use variable names as defined in the context.
        Example: "raster1 + raster2 * 2""
        """
        tree = ast.parse(expr, mode="eval")
        return self.visit(tree.body)  # evaluate the expression

    def analyze(self, expr):
        """
        Analyze a mathematical expression string to determine used variables and operations.
        """
        tree = ast.parse(expr, mode="eval")
        self.visit(tree.body)  # populate self.variables and self.operations

    def visit_BinOp(self, node):
        """Visit a binary operation node and evaluate it.
        This method supports only a limited set of operations defined in allowed_operators.
        It raises an error for unsupported operations.
        """
        self.operations.add(type(node.op))  # track the operation type
        left = self.visit(node.left)  # recursively visit left operand
        right = self.visit(node.right)  # recursively visit right operand
        op_type = type(node.op)
        if op_type in allowed_operators:
            return allowed_operators[op_type](left, right)  # perform the operation
        raise ValueError(f"Operator {op_type} not allowed")

    def visit_UnaryOp(self, node):
        """Visit a unary operation node and evaluate it.
        This method supports only the unary negation operator (-).
        It raises an error for unsupported unary operations.
        """
        self.operations.add(type(node.op))  # track the operation type
        operand = self.visit(node.operand)  # recursively visit the operand
        if isinstance(node.op, ast.USub):  # check for unary negation
            return -operand
        raise ValueError("Unsupported unary operator")

    def visit_Name(self, node):
        """Visit a variable name node and return its value from the context.
        This method also tracks the variable name for later dtype determination.
        If the variable is not found in the context, it raises a NameError.
        """
        self.variables.add(node.id)  # track the variable name
        if node.id in self.context:
            return self.context[node.id]
        raise NameError(f"Variable '{node.id}' not found")

    def visit_Constant(self, node):
        """Visit a constant value node and return its value."""
        return node.value

    def generic_visit(self, node):
        """Generic visit method for unsupported AST nodes.
        Raises a ValueError for any unsupported expression types.
        """
        raise ValueError(f"Unsupported expression: {ast.dump(node)}")

    def determine_output_dtype(self, expr):
        """
        After analyzing the expression, return a safe output dtype
        based on the variable dtypes and used operations.
        """
        self.variables.clear()  # Clear previously tracked variables and operations
        self.operations.clear()
        self.analyze(
            expr
        )  # Analyze the expression to populate variables and operations

        # Get dtypes of all raster variables
        var_dtypes = {}
        for var in self.variables:
            raster = self.context[var]
            var_dtypes[var] = raster.dtype

        input_dtypes = [
            np.dtype(dt) for dt in var_dtypes.values()
        ]  # Convert to numpy dtypes
        base_dtype = np.result_type(
            *input_dtypes
        )  # Determine base dtype from input dtypes

        # Operation-based promotion
        if ast.Div in self.operations:  # Division can lead to float output
            return np.float32
        if ast.Pow in self.operations:  # Power operation can lead to float output
            return np.float32
        if ast.Mult in self.operations:  # Multiplication can lead to float output
            if np.issubdtype(base_dtype, np.integer):
                return np.float32
        if (
            ast.Sub in self.operations or ast.USub in self.operations
        ):  # Subtraction can lead to signed integer output
            if np.issubdtype(base_dtype, np.unsignedinteger):
                if base_dtype == np.uint8:
                    return np.int16
                elif base_dtype == np.uint16:
                    return np.int32
                else:
                    return np.float32
        if ast.Add in self.operations:  # Addition can lead to unsigned integer output
            if np.issubdtype(base_dtype, np.unsignedinteger):
                if base_dtype == np.uint8:
                    return np.uint16
                elif base_dtype == np.uint16:
                    return np.uint32
                else:
                    return np.float32

        return base_dtype
