#!/usr/bin/env python3
"""Shell completion for the mibandd CLI.

`mibandd completion <shell>` prints a script; the script calls back into
`mibandd __complete <words...>` for candidates, so it always matches the
current command tree.
"""
import argparse

_SHELLS = ("bash", "zsh", "fish")


def _sub(parser):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None


def _options(parser):
    options = set()
    for action in parser._actions:
        options.update(action.option_strings)
    return options


def candidates(words, parser=None):
    """Completion candidates for the (partial) argv `words`."""
    if parser is None:
        from .main import client_parser
        parser = client_parser()
    root = parser
    current = root
    ancestors = [root]
    for word in words[:-1]:
        sub = _sub(current)
        if sub and word in sub.choices:
            current = sub.choices[word]
            ancestors.append(current)
    prefix = words[-1] if words else ""
    out = set()
    if prefix.startswith("-"):
        for ancestor in ancestors:
            out.update(_options(ancestor))
    else:
        sub = _sub(current) or _sub(root)
        if sub:
            out.update(name for name in sub.choices
                       if not name.startswith("_"))
    return sorted(c for c in out if c.startswith(prefix))


def script(shell):
    """The completion script for `shell` (bash/zsh/fish)."""
    if shell == "bash":
        return (
            "# mibandd bash completion\n"
            "# enable:  eval \"$(mibandd completion bash)\"\n"
            "_mibandd_complete() {\n"
            "    local IFS=$'\\n'\n"
            "    COMPREPLY=( $(mibandd __complete \"${COMP_WORDS[@]:1}\" "
            "2>/dev/null) )\n"
            "}\n"
            "complete -F _mibandd_complete mibandd\n"
        )
    if shell == "zsh":
        return (
            "# mibandd zsh completion\n"
            "# enable:  eval \"$(mibandd completion zsh)\"  (after compinit)\n"
            "_mibandd_complete() {\n"
            "    local -a cands\n"
            "    cands=(${(f)\"$(mibandd __complete ${words[2,-1]} "
            "2>/dev/null)\"})\n"
            "    compadd -- $cands\n"
            "}\n"
            "compdef _mibandd_complete mibandd\n"
        )
    if shell == "fish":
        return (
            "# mibandd fish completion\n"
            "# enable:  mibandd completion fish | source\n"
            "complete -c mibandd -f -a \"(mibandd __complete "
            "(commandline -opc | string match -v mibandd))\"\n"
        )
    raise ValueError(f"unknown shell {shell!r}; expected one of {_SHELLS}")
