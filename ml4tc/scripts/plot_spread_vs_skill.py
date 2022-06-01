"""Creates spread-skill plot and saves plot to image file."""

import argparse
import matplotlib
matplotlib.use('agg')
from matplotlib import pyplot
from gewittergefahr.gg_utils import file_system_utils
from ml4tc.utils import uq_evaluation
from ml4tc.plotting import uq_evaluation_plotting as uq_eval_plotting

FIGURE_RESOLUTION_DPI = 300

INPUT_FILE_ARG_NAME = 'input_file_name'
OUTPUT_FILE_ARG_NAME = 'output_file_name'

INPUT_FILE_HELP_STRING = (
    'Path to input file.  Will be read by `uq_evaluation.read_spread_vs_skill`.'
)
OUTPUT_FILE_HELP_STRING = (
    'Path to output file.  Figure will be saved as an image here.'
)

INPUT_ARG_PARSER = argparse.ArgumentParser()
INPUT_ARG_PARSER.add_argument(
    '--' + INPUT_FILE_ARG_NAME, type=str, required=True,
    help=INPUT_FILE_HELP_STRING
)
INPUT_ARG_PARSER.add_argument(
    '--' + OUTPUT_FILE_ARG_NAME, type=str, required=True,
    help=OUTPUT_FILE_HELP_STRING
)


def _run(input_file_name, output_file_name):
    """Creates spread-skill plot and saves plot to image file.

    This is effectively the main method.

    :param input_file_name: See documentation at top of file.
    :param output_file_name: Same.
    """

    file_system_utils.mkdir_recursive_if_necessary(file_name=output_file_name)

    print('Reading data from: "{0:s}"...'.format(input_file_name))
    result_dict = uq_evaluation.read_spread_vs_skill(input_file_name)

    figure_object, axes_object = uq_eval_plotting.plot_spread_vs_skill(
        result_dict=result_dict
    )

    if result_dict[uq_evaluation.USE_MEDIAN_KEY]:
        axes_object.set_ylabel('Skill (RMSE of median prediction)')
    else:
        axes_object.set_ylabel('Skill (RMSE of mean prediction)')

    this_string = 'Spread (stdev of predictive distribution,\ncomputed '
    if result_dict[uq_evaluation.USE_FANCY_QUANTILES_KEY]:
        this_string += 'with fancy quantile-based method)'
    else:
        this_string += 'the simple way)'

    axes_object.set_ylabel(this_string)

    title_string = 'Spread-skill plot (SSREL = {0:.2g})'.format(
        result_dict[uq_evaluation.SPREAD_SKILL_RELIABILITY_KEY]
    )
    print(title_string)
    axes_object.set_title(title_string)

    print('Saving figure to file: "{0:s}"...'.format(output_file_name))
    figure_object.savefig(
        output_file_name, dpi=FIGURE_RESOLUTION_DPI,
        pad_inches=0, bbox_inches='tight'
    )
    pyplot.close(figure_object)


if __name__ == '__main__':
    INPUT_ARG_OBJECT = INPUT_ARG_PARSER.parse_args()

    _run(
        input_file_name=getattr(INPUT_ARG_OBJECT, INPUT_FILE_ARG_NAME),
        output_file_name=getattr(INPUT_ARG_OBJECT, OUTPUT_FILE_ARG_NAME)
    )
