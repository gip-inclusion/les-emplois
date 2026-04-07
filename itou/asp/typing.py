import typing


class CodeComInsee(typing.TypedDict):
    # Yes, ASP has a top-level attribute named `codeComInsee` that is
    # a dictionary, which itself has an attribute of the same name.
    codeComInsee: str | None
    codeDpt: str


class AspBirthPlace(typing.TypedDict):
    codeComInsee: CodeComInsee
    codeInseePays: str | None
