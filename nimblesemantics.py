"""

The nimblesemantics module contains classes sufficient to perform a semantic analysis
of Nimble programs.

The analysis has two major tasks:

- to infer the types of all expressions in a Nimble program and to add appropriate type
annotations to the program's ANTLR-generated syntax tree by storing an entry in the `node_types`
dictionary for each expression node, where the key is the node and the value is a
`symboltable.PrimitiveType` or `symboltable.FunctionType`.

- to identify and flag all violations of the Nimble semantic specification
using the `errorlog.ErrorLog` and other classes in the `errorlog` module.

There are two phases to the analysis:

1. DefineScopesAndSymbols, and

2. InferTypesAndCheckSemantics.

In the first phase, `symboltable.Scope` objects are created for all scope-defining parse
tree nodes: the script, each function definition, and the main. These are stored in the
`self.scopes` dictionary. Also in this phase, all declared function types must be recorded
in the appropriate scope.

Parameter and variable types can be recorded in the appropriate scope in either the first
phase or the second phase.

In the second phase, type inference is performed and all other semantic constraints are
checked.


NOTES:
    - Turns out there's an easy way to access the PrimitiveTypes values with a TYPE's text:
        PrimitiveType['Int'] => PrimitiveType.Int. Thanks G-dawg.



Group members: OCdt Liethan Velasco and OCdt Aaron Brown
Version:    March 2nd, 2023

"""

# --- Importing other Modules ---

from errorlog import ErrorLog, Category
from nimble import NimbleListener, NimbleParser
from symboltable import PrimitiveType, FunctionType, Scope


# --- Defining Classes that contain exit and enter functions ---


class DefineScopesAndSymbols(NimbleListener):

    def __init__(self, error_log: ErrorLog, global_scope: Scope, types: dict):
        self.error_log = error_log
        self.current_scope = global_scope
        self.type_of = types

    def enterMain(self, ctx: NimbleParser.MainContext):
        self.current_scope = self.current_scope.create_child_scope('$main', PrimitiveType.Void)

    def exitMain(self, ctx: NimbleParser.MainContext):
        self.current_scope = self.current_scope.enclosing_scope

    def enterFuncDef(self, ctx: NimbleParser.FuncDefContext):
        # ! Stay in global scope, just create the function "symbol" and do nothing else

        # Get function name
        func_name = ctx.ID().getText();

        # EXTRACT types of parameters from each paramDef token
        # (Have to do this since we haven't created parameter symbols in function scope yet)
        param_types = [PrimitiveType[this_param.TYPE().getText()] for this_param in ctx.parameterDef()];

        # Get return type of function (default to void).
        ret_type = PrimitiveType.Void;
        if ctx.TYPE() is not None:
            ret_type = PrimitiveType[ctx.TYPE().getText()];

        # Create function type symbol in global scope.
        this_funcDef = FunctionType(param_types, ret_type);
        self.current_scope.define(func_name, this_funcDef)

        # Create the function's scope in the global scope
        self.current_scope.create_child_scope(ctx.ID().getText(), ret_type)


class InferTypesAndCheckConstraints(NimbleListener):
    """
    The type of each expression parse tree node is calculated and stored in the
    `self.type_of` dictionary, where the key is the node object, and the value is
    an instance of `symboltable.PrimitiveType`.

    The types of declared variables are stored in `self.variables`, which is a dictionary
    mapping from variable names to `symboltable.PrimitiveType` instances.

    Any semantic errors detected, e.g., undefined variable names,
    type mismatches, etc., are logged in the `error_log`
    """

    def __init__(self, error_log: ErrorLog, global_scope: Scope, types: dict):
        self.error_log = error_log
        self.current_scope = global_scope
        self.type_of = types

    def enterFuncDef(self, ctx: NimbleParser.FuncDefContext):

        # Switch scope to that of the function
        self.current_scope = self.current_scope.child_scope_named(ctx.ID().getText())
        # everything else gets handled at the lower levels.

    def exitFuncDef(self, ctx: NimbleParser.FuncDefContext):

        # Return to global scope
        self.current_scope = self.current_scope.enclosing_scope
        # Everything inside gets handled at lower levels.

    def sub_var_dec(self, ctx):

        # Extracting variable type declared, its primitive type, and the ID declared
        var_text = ctx.TYPE().getText()
        var_primtype = PrimitiveType[var_text]
        this_ID = ctx.ID().getText()

        # First thing to check is if we're declaring a duplicated variable name. Set ERROR if so and stop function.
        if self.current_scope.resolve(this_ID) is not None:
            self.current_scope.define(this_ID, PrimitiveType.ERROR, False)
            self.error_log.add(ctx, Category.DUPLICATE_NAME, f"Previously declared variable already has name"
                                                             f"[{this_ID}]. No duplicates are allowed.")
            error = True
        else:
            error = False

        return var_text, var_primtype, this_ID, error

    def exitParameterDef(self, ctx: NimbleParser.ParameterDefContext):
        # Create parameter symbol in the current scope (function scope)
        # similar to var dec
        var_text, var_primtype, this_ID, error = self.sub_var_dec(ctx)

        # create the symbol with the inputted type
        if not error:
            self.current_scope.define(this_ID, var_primtype, True)

    def exitReturn(self, ctx: NimbleParser.ReturnContext):

        # must match the function definition's type else create an error in the error log
        # in the main only a bare return can be used

        expr = ctx.expr()

        # checking if type matches function
        # (The type of the main function is PrimitiveType.Void)
        return_type = self.current_scope.return_type
        if return_type is not PrimitiveType.Void:
            if ctx.expr() is None:
                self.error_log.add(ctx, Category.INVALID_RETURN,
                                   f"ERROR: Function of type void cannot return something.")
            elif return_type != self.type_of[ctx.expr()]:
                self.error_log.add(ctx, Category.INVALID_RETURN,
                                   f"ERROR: Type returned ({self.type_of[ctx.expr()]}) does not match function "
                                   f"declaration type ({return_type}).")

        else:
            if expr is not None:
                self.error_log.add(ctx, Category.INVALID_RETURN,
                                   f"ERROR: Function declaration has return type ({PrimitiveType.Void}).")

    def exitFuncCall(self, ctx: NimbleParser.FuncCallContext):

        # ensure that the function exists within the global scope otherwise it's an error
        # ensure that argument types match the function's parameter types otherwise it's an error

        # Extracting tokens
        func_ID = ctx.ID().getText();
        func_args = [this_expr for this_expr in ctx.expr()];

        # First, check if a function with func_ID name exists. If none exists, set error accordingly and stop function
        func_symbol = self.current_scope.resolve(func_ID);
        if func_symbol is None:
            self.type_of[ctx] = PrimitiveType.ERROR;
            self.error_log.add(ctx, Category.INVALID_CALL, f"ERROR: A function with name {func_ID} does not exist. "
                                                           f"Check spelling or number of inputted arguments.");
            return;

        # If function exists, check argument types if matching with parameter types
        error_found = False;
        error_args = [];
        error_params = [];
        for this_arg, this_param_type in zip(func_args, func_symbol.type.parameter_types):

            # Check if a given argument does not match types with its respective parameter.
            # Find all mismatches and update error log accordingly.
            if self.type_of[this_arg] != this_param_type:
                error_args.append(f"{this_arg.getText()}:{self.type_of[this_arg]}");
                error_params.append(f"{this_param_type}");
                error_found = True;

        # If we found an error, set funcCall expression's type to ERROR.
        # Otherwise, set to return type of function
        if error_found:
            error_msg = f"ERROR: Argument(s) [{', '.join(error_args)}] do not " \
                        f"match respective expected function parameters types [{', '.join(error_params)}]."
            self.error_log.add(ctx, Category.INVALID_CALL, error_msg)
            self.type_of[ctx] = PrimitiveType.ERROR;
        else:
            self.type_of[ctx] = func_symbol.type.return_type;

    def exitFuncCallExpr(self, ctx: NimbleParser.FuncCallExprContext):
        # Need to assign it the type returned by the function
        # Checks if the type void
        _type = self.type_of[ctx.funcCall()]
        if _type == PrimitiveType.Void:
            self.error_log.add(ctx, Category.INVALID_CALL, "A void type function can not act as an expression.")
            self.type_of[ctx] = PrimitiveType.ERROR
            return
        self.type_of[ctx] = _type

    def exitFuncCallStmt(self, ctx: NimbleParser.FuncCallStmtContext):
        # Don't need to do anything here
        pass

    # --------------------------------------------------------
    # Program structure
    # --------------------------------------------------------

    def exitScript(self, ctx: NimbleParser.ScriptContext):
        # Doesn't need any semantic analysis or constraint checking.
        pass

    def enterMain(self, ctx: NimbleParser.MainContext):
        # Change current_scope field from $global -> $main
        self.current_scope = self.current_scope.child_scope_named('$main')

    def exitMain(self, ctx: NimbleParser.MainContext):
        # Change current_scope field from $main -> $global
        self.current_scope = self.current_scope.enclosing_scope

    def exitBody(self, ctx: NimbleParser.BodyContext):
        pass;

    def exitVarBlock(self, ctx: NimbleParser.VarBlockContext):
        # Doesn't need any semantic analysis or constraint checking.
        pass

    # Ohhhh yess it's "recursion time". Probably not the most elegant solution, but it's a solution :).
    def exitBlock(self, ctx: NimbleParser.BlockContext):

        # Search for a return statement in a given block node.
        # If one found, set all statements (if there are any) after the
        # return statement to unreachable.
        return_found = False;
        for this_statement in ctx.statement():

            if not return_found:

                # Check if current statement was a return
                if type(this_statement) == NimbleParser.ReturnContext:
                    return_found = True;

                # Check if current statement was a totally blocked if statement
                if type(this_statement) == NimbleParser.IfContext:
                    if self.check_if_totalblocked(this_statement):
                        return_found = True;

            # If return found, set all following statements to unreachable
            else:

                self.error_log.add(this_statement, Category.UNREACHABLE_STATEMENT,
                                   f"Statement [{this_statement.getText()}] is unreachable.");

                # If we encounter an if or while statement, descend into
                # their block nodes and set all their statements to unreachable.
                self.check_if_while_encountered(this_statement);

        # If current block node is a child of a function definition, check for missing return statements:
        # conduct second pass through all statements if there is a return or a totally blocked if-statement.
        # If so, all routes have a return statement. Otherwise, we have a missing return.
        if type(ctx.parentCtx.parentCtx) == NimbleParser.FuncDefContext:

            # Only check if function is not a void type.
            funcCtx = ctx.parentCtx.parentCtx;
            if funcCtx.TYPE() is not None:

                fully_blocked = False;
                for this_statement in ctx.statement():

                    if type(this_statement) == NimbleParser.IfContext:
                        if self.check_if_totalblocked(this_statement):
                            fully_blocked = True;

                    elif type(this_statement) == NimbleParser.ReturnContext:
                        fully_blocked = True;

                if not fully_blocked:
                    self.error_log.add(ctx, Category.MISSING_RETURN, f"Not all routes in block node "
                                                                     f"{ctx.getText()} have a return statement.");


    def check_if_totalblocked(self, this_if_statement):
        """ Checks if passed in this_if_statement is "totally blocked", meaning there
        is a return statement in all possible routes of the statement.

        Nimble code flow makes it so that anything after a totally blocked if
        statement in the block node is basically unreachable. In other words,
        a totally blocked if statement serves as a return statement.

        Returns: True if totally blocked. False otherwise. """

        # Booleans to track if return statement or totally blocked if found
        # in the if and else block of the statement. Default to False.
        if_blocked = False;
        else_blocked = False;

        # Check if an else block exists, if not, can't be totally blocked - return False.
        if this_if_statement.block(1) is None:
            return False;

        # Look through if-block
        for this_statement in this_if_statement.block(0).statement():

            # If we encounter another if statement, check if it's totally blocked.
            # If so, is basically a return statement.
            if type(this_statement) == NimbleParser.IfContext:
                if self.check_if_totalblocked(this_statement):
                    if_blocked = True;
                    break;

            # If we encounter a return statement at any point, if-block route is totally blocked
            elif type(this_statement) == NimbleParser.ReturnContext:
                if_blocked = True;
                break;

        # If the if-block is not totally blocked, no point in checking else-block for blockage.
        if if_blocked:

            # Look through else-block
            for this_statement in this_if_statement.block(1).statement():

                # If we encounter a fully blocked if-statement
                # If so, is basically a return statement.
                if type(this_statement) == NimbleParser.IfContext:
                    if self.check_if_totalblocked(this_statement):
                        else_blocked = True;
                        break;

                # If we encounter a return statement at any point, else-block route is totally blocked
                elif type(this_statement) == NimbleParser.ReturnContext:
                    else_blocked = True;
                    break;

        # Return true if all routes of if statement are blocked.
        if if_blocked and else_blocked:
            return True;
        else:
            return False;

    def check_if_while_encountered(self, this_statement):

        # Wrapper function to check if we encountered an if or while statement.
        # Descend into their blocks and set all their statements to unreachable.
        if type(this_statement) == NimbleParser.IfContext:
            self.set_if_unreachable(this_statement);
        elif type(this_statement) == NimbleParser.WhileContext:
            self.set_while_unreachable(this_statement);

    def set_while_unreachable(self, this_while):

        # Iterate through all statements in the block node...
        for this_statement in this_while.block().statement():
            # Set each as unreachable
            self.error_log.add(this_statement, Category.UNREACHABLE_STATEMENT,
                               f"Statement [{this_statement.getText()}] is unreachable.");

            # If we encounter another if or while statement, descend into
            # their block nodes and set all their statements to unreachable.
            self.check_if_while_encountered(this_statement);

    def set_if_unreachable(self, this_if):

        # Iterate through all statements of all its block nodes...
        for this_block in this_if.block():
            for this_statement in this_block.statement():
                # Set each as unreachable
                self.error_log.add(this_statement, Category.UNREACHABLE_STATEMENT,
                                   f"Statement [{this_statement.getText()}] is unreachable.");

                # If we encounter another if or while statement, descend into
                # their block nodes and set all their statements to unreachable.
                self.check_if_while_encountered(this_statement);

    def set_block_unreachable(self, this_node):

        for this_statement in this_node.block().statement():

            # Set each statement to unreachable.
            # If encounter another block, descend tree with recursion
            self.error_log.add(this_statement, Category.UNREACHABLE_STATEMENT,
                               f"Statement [{this_statement.getText()}] is unreachable.");

            if type(this_statement) == NimbleParser.BlockContext:
                self.set_block_unreachable(this_statement);

    # --------------------------------------------------------
    # Variable declarations
    # --------------------------------------------------------

    def exitVarDec(self, ctx: NimbleParser.VarDecContext):
        var_text, var_primtype, this_ID, error = self.sub_var_dec(ctx)

        # If no duplicate name, and if there was an assignment,
        # check if does not violate type constraint
        if ctx.expr() is not None:

            # Extract value of expression put for assignment
            expr_type = self.type_of[ctx.expr()]

            # Check if they match. If not, then there was a constraint violation
            if expr_type != var_primtype:
                self.current_scope.define(this_ID, PrimitiveType.ERROR, False)
                self.type_of[ctx] = PrimitiveType.ERROR
                self.error_log.add(ctx, Category.ASSIGN_TO_WRONG_TYPE,
                                   f"Can't assign {str(expr_type)} to variable of type {var_text}")
                return

        # If all input conditions met, create the symbol with the inuptted typeset the variable type accordingly
        if not error:
            self.current_scope.define(this_ID, var_primtype, False)

    # --------------------------------------------------------
    # Statements
    # --------------------------------------------------------

    def exitAssignment(self, ctx: NimbleParser.AssignmentContext):
        # The variable ID must already be declared, and be of the same type as
        # expr. If conditions are met, the variable symbol named ID takes on type of expr.
        # Otherwise, gets type ERROR

        this_ID = ctx.ID().getText()
        expr_type = self.type_of[ctx.expr()]
        symbol = self.current_scope.resolve(this_ID)

        # Checking if variable under ID has been declared. If not, record the error
        if symbol is None:
            self.error_log.add(ctx, Category.UNDEFINED_NAME, f"Can't assign value to undefined variable [{this_ID}]")
            return

        # Otherwise, check if expr_type does not match variable type. If not, record the error
        if symbol.type != expr_type:
            self.error_log.add(ctx, Category.ASSIGN_TO_WRONG_TYPE, f"Can't assign value of type {expr_type} to variable"
                                                                   f" [{this_ID}] of type {symbol.type}.")

    def exitWhile(self, ctx: NimbleParser.WhileContext):
        if self.type_of[ctx.expr()] != PrimitiveType.Bool:
            self.error_log.add(ctx, Category.CONDITION_NOT_BOOL, f"Type {self.type_of[ctx.expr()]} is not of type bool")

    def exitIf(self, ctx: NimbleParser.IfContext):
        # Simply check if the expr child is of type boolean. If not, record error
        if self.type_of[ctx.expr()] != PrimitiveType.Bool:
            self.error_log.add(ctx, Category.CONDITION_NOT_BOOL, f"if-statement condition [{ctx.expr().getText()}] "
                                                                 f"can only be of type {PrimitiveType.Bool}, not "
                                                                 f"{self.type_of[ctx.expr()]}.")

    def exitPrint(self, ctx: NimbleParser.PrintContext):
        # If expression to print is of type ERROR, record accordingly in error log.
        if self.type_of[ctx.expr()] == PrimitiveType.ERROR:
            self.error_log.add(ctx, Category.UNPRINTABLE_EXPRESSION, f"Can't print expression of type "
                                                                     f"{PrimitiveType.ERROR}.")

    # --------------------------------------------------------
    # Expressions
    # --------------------------------------------------------

    def exitIntLiteral(self, ctx: NimbleParser.IntLiteralContext):
        self.type_of[ctx] = PrimitiveType.Int

    def exitNeg(self, ctx: NimbleParser.NegContext):
        # Are conditions met for an integer negation?
        if ctx.op.text == '-' and self.type_of[ctx.expr()] == PrimitiveType.Int:
            self.type_of[ctx] = PrimitiveType.Int

        # Are conditions met for a boolean negation?
        elif ctx.op.text == '!' and self.type_of[ctx.expr()] == PrimitiveType.Bool:
            self.type_of[ctx] = PrimitiveType.Bool

        # If none, then error had occurred.
        else:
            self.type_of[ctx] = PrimitiveType.ERROR
            self.error_log.add(ctx, Category.INVALID_NEGATION,
                               f"Can't apply {ctx.op.text} to [{self.type_of[ctx].name}]")

    def exitParens(self, ctx: NimbleParser.ParensContext):
        self.type_of[ctx] = self.type_of[ctx.expr()]
        if self.type_of[ctx.expr()] == PrimitiveType.ERROR:
            self.error_log.add(ctx, Category.INVALID_BINARY_OP, f"Parentheses contain expression of "
                                                                f"type {PrimitiveType.ERROR}.")

    def exitMulDiv(self, ctx: NimbleParser.MulDivContext):
        left = self.type_of[ctx.expr(0)]
        right = self.type_of[ctx.expr(1)]
        if left == PrimitiveType.Int and right == PrimitiveType.Int:
            self.type_of[ctx] = PrimitiveType.Int
        else:
            self.type_of[ctx] = PrimitiveType.ERROR
            self.error_log.add(ctx, Category.INVALID_BINARY_OP,
                               f"Can't multiply or divide {self.type_of[ctx.expr(0)]} "
                               f"with/by {self.type_of[ctx.expr(1)]}")

    def exitAddSub(self, ctx: NimbleParser.AddSubContext):
        # If children types correct, set type of this token to Int
        if ((ctx.op.text == '+' or ctx.op.text == '-') and
                self.type_of[ctx.expr(0)] == PrimitiveType.Int and
                self.type_of[ctx.expr(1)] == PrimitiveType.Int):
            self.type_of[ctx] = PrimitiveType.Int

        # Otherwise, set as error.
        else:
            self.type_of[ctx] = PrimitiveType.ERROR
            self.error_log.add(ctx, Category.INVALID_BINARY_OP,
                               f"Can't apply {ctx.op.text} between non-integer type expression(s).")

    def exitCompare(self, ctx: NimbleParser.CompareContext):
        # Both left and right expressions must be integers. Results in a boolean type.
        # If these conditions are not met, error had occurred.
        left = self.type_of[ctx.expr(0)]
        right = self.type_of[ctx.expr(1)]
        if left == PrimitiveType.Int and right == PrimitiveType.Int:
            self.type_of[ctx] = PrimitiveType.Bool
        else:
            self.type_of[ctx] = PrimitiveType.ERROR
            self.error_log.add(ctx, Category.INVALID_BINARY_OP, f"Can't compare two non-integer type expressions.")

    def exitVariable(self, ctx: NimbleParser.VariableContext):
        # Simply check if ID is an existing var, or non-error type var.
        # If not, set type of ctx to be ERROR.
        this_ID = ctx.ID().getText()
        symbol = self.current_scope.resolve(this_ID)

        if symbol is None or symbol.type == PrimitiveType.ERROR:
            self.type_of[ctx] = PrimitiveType.ERROR
            self.error_log.add(ctx, Category.UNDEFINED_NAME,
                               f"Variable [{this_ID}] is undefined.")
        else:
            self.type_of[ctx] = symbol.type

    def exitStringLiteral(self, ctx: NimbleParser.StringLiteralContext):
        self.type_of[ctx] = PrimitiveType.String

    def exitBoolLiteral(self, ctx: NimbleParser.BoolLiteralContext):
        self.type_of[ctx] = PrimitiveType.Bool
