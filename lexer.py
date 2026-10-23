# lexer.py - simple tokenizer for C-subset language
from collections import namedtuple

Token = namedtuple("Token", ["type", "text", "line", "col"])

KEYWORDS = {"int", "float", "if", "else", "while", "for", "switch", "case", "default", "break"}
TWO_CHAR_OPS = {"<=", ">=", "==", "!="}
SYMBOLS = set("+-*/<>=;,:)({}")

class LexerError(SyntaxError):
    def __init__(self, message, line, col, errors=None):
        super().__init__(message)
        self.message = message
        self.line = line
        self.col = col
        self.errors = errors or [(line, col, message)]

def tokenize(src):
    tokens = []
    i = 0
    n = len(src)
    line = 1
    col = 1
    lexer_errors = []

    while i < n:
        ch = src[i]

        if ch in " \t\r":
            i += 1
            col += 1
            continue

        if ch == "\n":
            i += 1
            line += 1
            col = 1
            continue

        # 2-char operators
        if i + 1 < n and src[i:i+2] in TWO_CHAR_OPS:
            op = src[i:i+2]
            tokens.append(Token(op, op, line, col))
            i += 2
            col += 2
            continue

        # 1-char symbols and operators
        if ch in SYMBOLS:
            tokens.append(Token(ch, ch, line, col))
            i += 1
            col += 1
            continue

        # identifiers and keywords
        if ch.isalpha() or ch == "_":
            start_col = col
            val = ""
            while i < n and (src[i].isalnum() or src[i] == "_"):
                val += src[i]
                i += 1
                col += 1
            ttype = val if val in KEYWORDS else "id"
            tokens.append(Token(ttype, val, line, start_col))
            continue

        # numbers (intlit and floatlit)
        if ch.isdigit():
            start_col = col
            val = ""
            while i < n and src[i].isdigit():
                val += src[i]
                i += 1
                col += 1
            if i < n and src[i] == "." and i + 1 < n and src[i+1].isdigit():
                val += "."
                i += 1
                col += 1
                while i < n and src[i].isdigit():
                    val += src[i]
                    i += 1
                    col += 1
                tokens.append(Token("floatlit", val, line, start_col))
            else:
                tokens.append(Token("intlit", val, line, start_col))
            continue

        # Collect unknown character error and continue scanning to find all errors
        err_msg = f"Lexer error at line {line}, col {col}: unknown character '{ch}'"
        lexer_errors.append((line, col, err_msg))
        i += 1
        col += 1

    if lexer_errors:
        first_line, first_col, first_msg = lexer_errors[0]
        raise LexerError(first_msg, first_line, first_col, errors=lexer_errors)

    tokens.append(Token("$", "$", line, col))
    return tokens


