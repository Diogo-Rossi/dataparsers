# %% ################################################# dataparsers region ######################################################
import os, textwrap
from dataclasses import dataclass, field, fields
from argparse import ArgumentParser, RawTextHelpFormatter
from argparse import _MutuallyExclusiveGroup, _ArgumentGroup, _SubParsersAction  # only for typing annotation
from typing import Any, TypeVar, Sequence, Callable, overload, ClassVar, get_type_hints, get_origin

Class = TypeVar("Class", covariant=True)


def arg(
    *name_or_flags: str,
    group_title: str | int | None = None,
    mutually_exclusive_group_id: str | int | None = None,
    make_flag: bool | None = None,
    **kwargs,
) -> Any:
    is_flag = False

    if name_or_flags:
        if not all(n.startswith("-") for n in name_or_flags):
            raise ValueError(
                "The argument `name_or_flags` should be passed to function `arg` only if it is a flag (starts with `-`)"
            )
        if not any(n.startswith("--") for n in name_or_flags) and make_flag is None:
            make_flag = True
        is_flag = True

    if "dest" in kwargs:
        raise ValueError("The argument `dest` is not necessary")

    if "default" in kwargs and not kwargs.get("nargs", None) in ["?", "*"] and not is_flag:
        make_flag = True

    default = kwargs.pop("default", None)

    if not is_flag and mutually_exclusive_group_id is not None:
        make_flag = True

    make_flag = bool(make_flag)
    is_flag = is_flag or make_flag

    metadict = dict(
        name_or_flags=name_or_flags,
        group_title=group_title,
        mutually_exclusive_group_id=mutually_exclusive_group_id,
        is_flag=is_flag,
        make_flag=make_flag,
        **kwargs,
    )

    metadict = {key: value for key, value in metadict.items() if value is not None}

    return field(default=default, metadata=metadict)


def group(*args, **kwargs) -> Any:
    argument_group_kwargs = dict(**{k: v for k, v in zip(["title", "description"], args)}, **kwargs)
    return field(metadata={"argument_group_kwargs": argument_group_kwargs})


def mutually_exclusive_group(**kwargs) -> Any:
    return field(metadata={"mutually_exclusive_group_kwargs": kwargs})


def subparsers(**kwargs) -> Any:
    return field(default=None, metadata={"is_subparsers_group": True, "subparsers_group_kwargs": kwargs})


def default(default=None):
    return field(default=default, metadata={"is_post_default": True})


@dataclass(frozen=True)
class SubParser:
    defaults: dict[str, Any] | None
    kwargs: dict[str, Any]


def subparser(*, defaults: dict[str, Any] | None = None, **kwargs) -> Any:
    return SubParser(defaults=defaults, kwargs=kwargs)


@overload
def dataparser(cls: type[Class]) -> type[Class]: ...


@overload
def dataparser(
    *,
    groups_descriptions: dict[str | int, str] | None = None,
    required_mutually_exclusive_groups: dict[str | int, bool] | None = None,
    default_bool: bool = False,
    **kwargs,
) -> Callable[[type[Class]], type[Class]]: ...


def dataparser(
    cls: type[Class] | None = None,
    *,
    groups_descriptions: dict[str | int, str] | None = None,
    required_mutually_exclusive_groups: dict[str | int, bool] | None = None,
    default_bool: bool = False,
    help_formatter: Callable[[str], str] | None = None,
    **kwargs,
) -> type[Class] | Callable[[type[Class]], type[Class]]:
    if cls is not None:
        return dataclass(cls)

    if groups_descriptions is None:
        groups_descriptions = {}

    if required_mutually_exclusive_groups is None:
        required_mutually_exclusive_groups = {}

    def wrap(cls: type[Class]) -> type[Class]:
        cls = dataclass(cls)
        setattr(
            cls,
            "__dataparsers_params__",
            (kwargs, groups_descriptions, required_mutually_exclusive_groups, default_bool, help_formatter),
        )
        return cls

    return wrap


def make_parser(cls: type, *, parser: ArgumentParser | None = None) -> ArgumentParser:
    kwargs, groups_descriptions, required_groups_status, default_bool, help_formatter = getattr(
        cls, "__dataparsers_params__", ({}, {}, {}, False, None)
    )

    if parser is None:
        if help_formatter is not None and "formatter_class" not in kwargs:
            kwargs["formatter_class"] = RawTextHelpFormatter
        parser = ArgumentParser(**kwargs)

    help_formatter = help_formatter or str
    groups: dict[str | int, _ArgumentGroup] = {}
    mutually_exclusive_groups: dict[str | int, _MutuallyExclusiveGroup] = {}
    subparsers: dict[str, ArgumentParser] = {}
    subparsers_group: _SubParsersAction | None = None

    for fld in fields(cls):  # type: ignore
        if type(fld.type) == str:
            fld.type = eval(fld.type)

        if fld.metadata.get("is_subparsers_group", False):
            subparsers_group_kwargs = fld.metadata.get("subparsers_group_kwargs", {})
            subparsers_group_kwargs.pop("dest", None)
            subparsers_group = parser.add_subparsers(dest=fld.name, **subparsers_group_kwargs)

    handler = parser
    classvars = {k: v for (k, v) in get_type_hints(cls).items() if v == ClassVar or get_origin(v) is ClassVar}
    for field_name in classvars:
        attr = getattr(cls, field_name)
        if isinstance(attr, SubParser):
            subparsers_kwargs = attr.kwargs.get("subparsers_kwargs", {})
            subparser_defaults = attr.defaults
            if subparsers_group is None:
                subparsers_group = handler.add_subparsers()
            if field_name not in subparsers:
                subparsers[field_name] = subparsers_group.add_parser(field_name, **subparsers_kwargs)
                if subparser_defaults is not None:
                    subparsers[field_name].set_defaults(**subparser_defaults)

    for fld in fields(cls):  # type: ignore
        if type(fld.type) == str:
            fld.type = eval(fld.type)
        arg_metadata = dict(fld.metadata)

        if "help" in arg_metadata:
            arg_metadata["help"] = help_formatter(arg_metadata["help"])

        arg_field_has_default = fld.default is not fld.default_factory
        make_flag = arg_metadata.pop("make_flag", True)
        if (arg_field_has_default and arg_metadata.pop("is_flag", True)) or fld.type == bool:
            if "name_or_flags" not in arg_metadata:
                arg_metadata["name_or_flags"] = ()
            if make_flag or (fld.type == bool and not arg_metadata["name_or_flags"]):
                arg_metadata["name_or_flags"] += (f'--{fld.name.replace("_", "-")}',)
            if fld.type == bool and (not arg_field_has_default or fld.default is None):
                fld.default = default_bool

        if not arg_metadata.get("name_or_flags"):  # no flag arg
            arg_metadata["name_or_flags"] = (fld.name,)
        else:  # flag arg
            arg_metadata["dest"] = fld.name

        name_or_flags = arg_metadata.pop("name_or_flags")

        if "type" not in arg_metadata and fld.type != bool:
            arg_metadata["type"] = fld.type

        if "action" not in arg_metadata and fld.type == bool:
            arg_metadata["action"] = "store_false" if fld.default else "store_true"

        if fld.type == bool:
            fld.default = arg_metadata["action"] == "store_false"

        group_id: str | int | None = arg_metadata.pop("group_title", None)
        exclusive_group_id: str | int | None = arg_metadata.pop("mutually_exclusive_group_id", None)
        if any(id is not None for id in [group_id, exclusive_group_id]):

            handler = parser

            if group_id is not None:
                if group_id not in groups:
                    groups[group_id] = parser.add_argument_group(
                        title=group_id if type(group_id) == str else None,
                        description=groups_descriptions.get(group_id, None),
                    )

                handler = groups[group_id]

            if exclusive_group_id is not None:

                if exclusive_group_id not in mutually_exclusive_groups:
                    mutually_exclusive_groups[exclusive_group_id] = handler.add_mutually_exclusive_group(
                        required=required_groups_status.get(exclusive_group_id, False),
                    )

                handler = mutually_exclusive_groups[exclusive_group_id]

            handler.add_argument(*name_or_flags, default=fld.default, **arg_metadata)

        else:
            parser.add_argument(*name_or_flags, default=fld.default, **arg_metadata)

    return parser


def parse(cls: type[Class], args: Sequence[str] | None = None, *, parser: ArgumentParser | None = None) -> Class:
    return cls(**vars(make_parser(cls, parser=parser).parse_args(args)))


def write_help(
    text: str,
    width: int | None = None,
    space: int = 24,
    dedent: bool = True,
    final_newlines: bool = True,
) -> str:
    width = width or os.get_terminal_size().columns
    lines = []
    for line in text.splitlines():
        line = textwrap.dedent(line) if dedent else line
        lines.append(textwrap.fill(text=line, width=width - space, replace_whitespace=False))

    return "\n".join(lines) + ("\n\n" if final_newlines else "")


# %% ###########################################################################################################################
