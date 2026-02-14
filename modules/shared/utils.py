import re

def sanitize_input_string(text: str) -> str:
    """
    Sanitizes an input string by removing common "finger error" characters 
    from the START and END of the string.
    Does NOT modify the internal content of the string.
    
    Removes: Spaces, dots, pipes, commas, dashes, underscores, asterisks, slashes, backslashes,
    plus signs, quotes, colons, semicolons, equals, exclamation marks, question marks,
    hashes, percent signs, ampersands, ats, parentheses, brackets, braces, angle brackets,
    tildes, backticks.

    Examples:
      "| Project Alpha - ." -> "Project Alpha"
      "  User Name  " -> "User Name"
      "/Path/To/Something/" -> "Path/To/Something"
      "+IZTAPALA" -> "IZTAPALA"
      "[Draft] Project X" -> "Draft] Project X"
    """
    if not text:
        return ""
        
    # Regex for "dirty" characters at the edges
    # \s = whitespace
    # \. = dot
    # \| = pipe
    # , = comma
    # \- = dash
    # _ = underscore
    # \* = asterisk
    # / = forward slash
    # \\ = backslash
    # \+ = plus
    # \" = double quote
    # \' = single quote
    # : = colon
    # ; = semicolon
    # = = equal
    # ! = exclamation
    # \? = question mark
    # # = hash
    # % = percent
    # & = ampersand
    # @ = at
    # \( \) = parentheses
    # \[ \] = brackets
    # \{ \} = braces
    # < > = angle brackets
    # ~ = tilde
    # ` = backtick
    dirty_pattern = r"^[\s\.|,_*/\\\+\-\"\':;=!\?#%&@\(\)\[\]\{\}<>~`]+|[\s\.|,_*/\\\+\-\"\':;=!\?#%&@\(\)\[\]\{\}<>~`]+$"
    
    return re.sub(dirty_pattern, "", text).strip()
