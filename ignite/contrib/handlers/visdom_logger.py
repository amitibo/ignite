from ignite.engine import Engine
from ignite.engine import Events
import os
import numpy as np
from typing import Callable, List


class VisdomLogger:
    """Handler that plots metrics using Visdom graphs.

    The `VisdomLogger` can be used to plot to multiple windows each one with a different
    set of metrics.

    Args:
        vis (Visdom object, optional): Visdom client.
        server (str, optinal): URL of visdom server.
        env (str, optional): Name of Visdom environment for the graphs. Defaults to "main".
        log_to_filename (str, optional): If given, the plots will be also be save to a file
            by this name. Later this graphs can be replayed from this file.
        save_by_default (bool, optional): The graphs will be saved by default by the server.

    Note:
        The visdom server can be set by passing an already configured visdom client (using
        the `vis` argument). Alternatively, the URL of the server can be passed using
        the `server` argument or by setting the `VISDOM_SERVER_URL` environment variable.
        By default, when none of these methods is used, the constructor will try to connect
        to `http://localhost`.

    Examples:

    Plotting of trainer loss.

    .. code-block:: python

        trainer = create_supervised_trainer(model, optimizer, loss)

        visdom_plotter = VisdomLogger(vis, env=env)

        visdom_plotter.create_window(
            engine=trainer,
            window_title="Training Losses",
            xlabel="epoch",
            plot_event=Events.ITERATION_COMPLETED,
            update_period=LOG_INTERVAL,
            output_transform=lambda x: {"loss": x}
        )

    Attach validation metrics

    .. code-block:: python

        metrics={
            'accuracy': CategoricalAccuracy(),
            'nll': Loss(loss)
        }
        evaluator = create_supervised_evaluator(
            model,
            metrics=metrics
        )

        visdom_plotter = VisdomLogger(vis, env=env)

        visdom_plotter.create_window(
            engine=evaluator,
            window_title="Evaluation",
            xlabel="epoch",
            plot_event=Events.EPOCH_COMPLETED,
            metric_names=list(metrics.keys())
        )

    """

    def __init__(
        self,
        vis=None,              # type: visdom.Visdom
        server=None,           # type: str
        env="main",            # type: str
        log_to_filename=None,  # type: str
        save_by_default=True,  # type: bool
    ):

        try:
            import visdom
        except ImportError:
            raise RuntimeError("No visdom package is found. Please install it with command: \n pip install visdom")

        if vis is None:
            if server is None:
                server = os.environ.get("VISDOM_SERVER_URL", 'http://localhost')

            vis = visdom.Visdom(
                server=server,
                log_to_filename=log_to_filename,
            )

        if not vis.check_connection():
            raise RuntimeError("Failed to connect to Visdom server at {}. " \
                               "Did you run python -m visdom.server ?".format(server))

        self.vis = vis
        self.env = env
        self.save_by_default = save_by_default
        self.plots = dict()
        self.metrics_step = []

    def _update(
        self,
        engine,                 # type: Engine
        attach_id,              # type: int
        window_title,           # type: str
        window_opts,            # type: dict
        update_period,          # type: int
        metric_names=None,      # type: List
        output_transform=None,  # type: Callable
    ):

        step = self.metrics_step[attach_id]
        if type(step) is int:
            self.metrics_step[attach_id] += 1
            if step % update_period != 0:
                return
        else:
            step = step(engine.state)

        #
        # Get all the metrics
        #
        metrics = []
        if metric_names is not None:
            if not all(metric in engine.state.metrics for metric in metric_names):
                raise KeyError("metrics not found in engine.state.metrics")

            metrics.extend([(name, engine.state.metrics[name]) for name in metric_names])

        if output_transform is not None:
            output_dict = output_transform(engine.state.output)

            if not isinstance(output_dict, dict):
                output_dict = {"output": output_dict}

            metrics.extend([(name, value) for name, value in output_dict.items()])

        if not metrics:
            return

        metric_names, metric_values = list(zip(*metrics))
        line_opts = window_opts.copy()
        line_opts['legend'] = list(metric_names)

        if window_title not in self.plots:
            win = self.vis.line(
                X=np.array([step] * len(metric_values)).reshape(1, -1),
                Y=np.array(metric_values).reshape(1, -1),
                env=self.env,
                opts=line_opts
            )
            self.plots[window_title] = win

        else:
            self.vis.line(
                X=np.array([step] * len(metric_values)).reshape(1, -1),
                Y=np.array(metric_values).reshape(1, -1),
                env=self.env,
                opts=line_opts,
                win=self.plots[window_title],
                update='append'
            )

        if self.save_by_default:
            self.vis.save([self.env])

    def create_window(
        self,
        engine,                             # type: Engine
        window_title="Metrics",             # type: str
        xlabel="epoch",                     # type: str
        ylabel="value",                     # type: str
        show_legend=False,                  # type: bool
        plot_event=Events.EPOCH_COMPLETED,  # type: Events
        update_period=1,                    # type: int
        metric_names=None,                  # type: List
        output_transform=None,              # type: Callable
        step_callback=None,                 # type: Callable
    ):
        """
        Creates a Visdom window and attaches it to an engine object

        Args:
            engine (Engine): engine object
            window_title (str, optional): The title that will given to the window.
            xlabel (str, optional): Label of the x-axis.
            ylabel (str, optional): Label of the y-axis.
            show_legend (bool, optional): Whether to add a legend to the window,
            plot_event (str, optional): Name of event to handle.
            update_period (int, optional): Can be used to limit the number of plot updates.
            metric_names (list, optional): list of the metrics names to plot.
            output_transform (Callable, optional): a function to select what you want to plot from the engine's
                output. This function may return either a dictionary with entries in the format of ``{name: value}``,
                or a single scalar, which will be displayed with the default name `output`.
            step_callback (Callable, optional): a function to select what to use as the x value (step) from the engine's
                state. This function should return a single scalar.
        """
        if metric_names is not None and not isinstance(metric_names, list):
            raise TypeError("metric_names should be a list, got {} instead".format(type(metric_names)))

        if output_transform is not None and not callable(output_transform):
            raise TypeError("output_transform should be a function, got {} instead"
                            .format(type(output_transform)))

        if step_callback is not None and not callable(step_callback):
            raise TypeError("step_callback should be a function, got {} instead"
                            .format(type(step_callback)))

        assert plot_event in (Events.ITERATION_COMPLETED, Events.EPOCH_COMPLETED), \
            "The plotting event should be either {} or {}".format(Events.ITERATION_COMPLETED, Events.EPOCH_COMPLETED)

        window_opts = dict(
            title=window_title,
            xlabel=xlabel,
            ylabel=ylabel,
            showlegend=show_legend
        )

        attach_id = len(self.metrics_step)

        if step_callback is None:
            self.metrics_step.append(0)
        else:
            self.metrics_step.append(step_callback)

        engine.add_event_handler(
            plot_event,
            self._update,
            attach_id=attach_id,
            window_title=window_title,
            window_opts=window_opts,
            update_period=update_period,
            metric_names=metric_names,
            output_transform=output_transform
        )
