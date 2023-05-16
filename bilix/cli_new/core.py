"""
use handler to provide click(typer) cli service
"""
from typing import List, Optional, Union, get_origin, get_args, Annotated
from click import UsageError, Context, Command
from typer.models import OptionInfo, ParameterInfo, ParamMeta
from typer.core import TyperCommand, TyperOption, TyperArgument
from typer.main import get_click_param
from bilix.cli_new.assign import assign
from bilix.cli_new.handler import ParamInfo
from bilix.log import logger


def to_typer_param_meta(p: ParamInfo) -> ParamMeta:
    annotation = p.annotation
    default = p.default

    if annotation == p.empty and default != p.empty:
        annotation = type(default)
    elif (origin := get_origin(annotation)) is Union:
        annotation = get_args(annotation)[0]  # use the first type in Union, it's a convention
    elif origin is Annotated:
        # base_annotation, *convertors = get_args(annotation)
        # todo metavar
        annotation = str
    # convert default to OptionInfo to ensure no ArgumentInfo is created
    if not isinstance(default, ParameterInfo):
        default = OptionInfo(default=... if default == p.empty else default, help=p.desc)
    return ParamMeta(name=p.name, annotation=annotation, default=default)


def get_click_option(p: ParamInfo) -> Optional[TyperOption]:
    """
    typer get_click_param with some logic to handle more cases
    """
    p = to_typer_param_meta(p)
    try:
        option, convertor = get_click_param(p)
        if convertor:
            logger.debug(f"ignore {convertor}")
        return option
    except RuntimeError as e:
        logger.debug(e)
    except AssertionError as e:
        logger.debug(e)
    assert p.default != p.empty, f"Parameter '{p.name}' has no available type hint and no default value."


class CustomContext(Context):
    @property
    def command_path(self) -> str:
        """The computed command path.  This is used for the ``usage``
        information on the help page.  It's automatically created by
        combining the info names of the chain of contexts to the root.
        """
        rv = ""
        if self.info_name is not None:
            rv = self.info_name
        if self.parent is not None:
            parent_command_path = [self.parent.command_path]

            if isinstance(self.parent.command, Command):
                for param in self.parent.command.get_params(self):
                    parent_command_path.extend(param.get_usage_pieces(self))

            rv = f"{' '.join(parent_command_path)} {rv}"
        res = rv.lstrip()
        if self.obj:
            method, keys = self.obj['method'], self.obj['keys']
            return f"{res} {method.short if method.short else method.name} KEYS..."
        else:
            return res


class CustomCommand(TyperCommand):
    context_class = CustomContext

    def parse_args(self, ctx: Context, args: List[str]):
        if '--debug' in args:  # preparse debug option to ensure log assign debug info
            logger.setLevel('DEBUG')
            logger.debug("Debug on, more information will be shown")
        try:
            method, keys = self._find_method_keys(ctx, args)
        except UsageError:
            return super().parse_args(ctx, args)
        handler_cls = assign(method, keys)
        cli_info = handler_cls.cli_info
        method = cli_info[method]
        # add dynamic_params to ctx
        ctx.ensure_object(dict)
        ctx.obj["init_options"] = []
        ctx.obj["method_options"] = []
        ctx.obj['method'] = method
        ctx.obj['keys'] = keys
        # for handler init
        for p in cli_info['__init__'].params.values():
            if option := get_click_option(p):
                option.rich_help_panel = f"Options for {handler_cls.__name__}"
                self.params.append(option)
                ctx.obj["init_options"].append(option.name)
        # for method
        ps = list(method.params.values())
        # skip key
        for p in ps[1:]:
            if option := get_click_option(p):
                option.rich_help_panel = f"Options for {method.name} (alias: {method.short})"
                self.params.append(option)
                ctx.obj["method_options"].append(option.name)
        ctx.obj['handler_cls'] = handler_cls

        self.params.append(TyperArgument(param_decls=['method'], type=str, required=True, hidden=True,
                                         # metavar=f'{method.name} ({method.short})' if method.short else method.name,
                                         ))
        self.params.append(TyperArgument(param_decls=['keys'], type=str, required=True, nargs=-1, help=ps[0].desc, ))
        self.help = '✨ ' + method.desc
        try:
            return super().parse_args(ctx, args)
        except UsageError as e:
            e.message = f"[For {handler_cls.__name__} {method.name}] {e.message}"
            raise

    @staticmethod
    def _find_method_keys(ctx, args):
        if len(args) == 0:
            raise UsageError("method is required", ctx)
        for idx, arg in enumerate(args):
            if arg.startswith('-'):
                if idx == 0:
                    raise UsageError("method should be first", ctx)
                return args[0], args[1:idx]
        return args[0], args[1:]

    def collect_usage_pieces(self, ctx: Context) -> List[str]:
        """basically copy from click.core.Command.collect_usage_pieces, but with option metavar moved to the end"""
        rv = []
        # for param in self.get_params(ctx):
        #     rv.extend(param.get_usage_pieces(ctx))
        if self.options_metavar:
            rv.append(self.options_metavar)
        return rv