"""Matches CNN predictions to SHIPS predictions."""

import argparse
import numpy
from gewittergefahr.gg_utils import longitude_conversion as lng_conversion
from ml4tc.io import prediction_io
from ml4tc.io import ships_prediction_io
from ml4tc.machine_learning import neural_net

MAX_DISTANCE_DEG = 1.

CNN_FILE_ARG_NAME = 'input_cnn_prediction_file_name'
SHIPS_FILE_ARG_NAME = 'input_ships_prediction_file_name'
USE_RI_CONSENSUS_ARG_NAME = 'use_ri_consensus'
USE_TD_TO_TS_LGE_ARG_NAME = 'use_td_to_ts_lge'
OUTPUT_FILE_ARG_NAME = 'output_ships_prediction_file_name'

CNN_FILE_HELP_STRING = (
    'Path to file with CNN predictions.  Will be read by '
    '`prediction_io.read_file`.'
)
SHIPS_FILE_HELP_STRING = (
    'Path to file with SHIPS predictions.  Will be read by '
    '`ships_prediction_io.read_ri_file` or '
    '`ships_prediction_io.read_td_to_ts_file`.'
)
USE_RI_CONSENSUS_HELP_STRING = (
    '[used only if files contain rapid-intensification predictions] Boolean '
    'flag.  If 1 (0), will use consensus (SHIPS-RII) model from SHIPS files.'
)
USE_TD_TO_TS_LGE_HELP_STRING = (
    '[used only if files contain TD-to-TS predictions] Boolean flag.  If 1 (0),'
    ' will use LGE (basic with land included) model from SHIPS files.'
)
OUTPUT_FILE_HELP_STRING = (
    'Path to output file.  SHIPS predictions matched with CNN predictions will '
    'be written here by `prediction_io.write_file`.'
)

INPUT_ARG_PARSER = argparse.ArgumentParser()
INPUT_ARG_PARSER.add_argument(
    '--' + CNN_FILE_ARG_NAME, type=str, required=True,
    help=CNN_FILE_HELP_STRING
)
INPUT_ARG_PARSER.add_argument(
    '--' + SHIPS_FILE_ARG_NAME, type=str, required=True,
    help=SHIPS_FILE_HELP_STRING
)
INPUT_ARG_PARSER.add_argument(
    '--' + USE_RI_CONSENSUS_ARG_NAME, type=int, required=True,
    help=USE_RI_CONSENSUS_HELP_STRING
)
INPUT_ARG_PARSER.add_argument(
    '--' + USE_TD_TO_TS_LGE_ARG_NAME, type=int, required=True,
    help=USE_TD_TO_TS_LGE_HELP_STRING
)
INPUT_ARG_PARSER.add_argument(
    '--' + OUTPUT_FILE_ARG_NAME, type=str, required=True,
    help=OUTPUT_FILE_HELP_STRING
)


def _match_examples(cnn_prediction_dict, ships_prediction_dict):
    """Matches each CNN example to 0 or 1 SHIPS examples.

    E = number of examples matched

    :param cnn_prediction_dict: Dictionary read by `prediction_io.read_file`.
    :param ships_prediction_dict: Dictionary read by
        `ships_prediction_io.read_ri_file` or
        `ships_prediction_io.read_td_to_ts_file`.
    :return: cnn_indices: length-E numpy array of indices in CNN dictionary.
    :return: ships_indices: length-E numpy array of indices in SHIPS dictionary.
    """

    ships_init_times_unix_sec = (
        ships_prediction_dict[ships_prediction_io.INIT_TIMES_KEY]
    )
    ships_latitudes_deg_n = (
        ships_prediction_dict[ships_prediction_io.INIT_LATITUDES_KEY]
    )
    ships_pos_longitudes_deg_e = lng_conversion.convert_lng_positive_in_west(
        ships_prediction_dict[ships_prediction_io.INIT_LONGITUDES_KEY]
    )
    ships_neg_longitudes_deg_e = lng_conversion.convert_lng_negative_in_west(
        ships_prediction_dict[ships_prediction_io.INIT_LONGITUDES_KEY]
    )

    cnn_init_times_unix_sec = cnn_prediction_dict[prediction_io.INIT_TIMES_KEY]
    cnn_latitudes_deg_n = cnn_prediction_dict[prediction_io.STORM_LATITUDES_KEY]
    cnn_pos_longitudes_deg_e = lng_conversion.convert_lng_positive_in_west(
        cnn_prediction_dict[prediction_io.STORM_LONGITUDES_KEY]
    )
    cnn_neg_longitudes_deg_e = lng_conversion.convert_lng_negative_in_west(
        cnn_prediction_dict[prediction_io.STORM_LONGITUDES_KEY]
    )

    num_cnn_examples = len(cnn_init_times_unix_sec)
    cnn_to_ships_indices = numpy.full(num_cnn_examples, -1, dtype=int)

    for i in range(num_cnn_examples):
        js = numpy.where(
            ships_init_times_unix_sec == cnn_init_times_unix_sec[i]
        )[0]

        if len(js) == 0:
            continue

        first_distances_deg = numpy.sqrt(
            (cnn_latitudes_deg_n[i] - ships_latitudes_deg_n[js]) ** 2 +
            (cnn_pos_longitudes_deg_e[i] - ships_pos_longitudes_deg_e[js]) ** 2
        )
        second_distances_deg = numpy.sqrt(
            (cnn_latitudes_deg_n[i] - ships_latitudes_deg_n[js]) ** 2 +
            (cnn_neg_longitudes_deg_e[i] - ships_neg_longitudes_deg_e[js]) ** 2
        )
        these_distances_deg = numpy.minimum(
            first_distances_deg, second_distances_deg
        )

        if numpy.min(these_distances_deg) > MAX_DISTANCE_DEG:
            continue

        cnn_to_ships_indices[i] = js[numpy.argmin(these_distances_deg)]

    cnn_indices = numpy.where(cnn_to_ships_indices >= 0)[0]
    ships_indices = cnn_to_ships_indices[cnn_indices]

    print('Matched {0:d} of {1:d} CNN examples to a SHIPS example!'.format(
        len(cnn_indices), num_cnn_examples
    ))

    return cnn_indices, ships_indices


def _run(cnn_prediction_file_name, ships_prediction_file_name,
         use_ri_consensus, use_td_to_ts_lge, output_file_name):
    """Matches CNN predictions to SHIPS predictions.

    This is effectively the main method.

    :param cnn_prediction_file_name: See documentation at top of file.
    :param ships_prediction_file_name: Same.
    :param use_ri_consensus: Same.
    :param use_td_to_ts_lge: Same.
    :param output_file_name: Same.
    """

    print('Reading CNN predictions from: "{0:s}"...'.format(
        cnn_prediction_file_name
    ))
    cnn_prediction_dict = prediction_io.read_file(cnn_prediction_file_name)

    model_metafile_name = neural_net.find_metafile(
        model_file_name=cnn_prediction_dict[prediction_io.MODEL_FILE_KEY],
        raise_error_if_missing=True
    )

    print('Reading CNN metadata from: "{0:s}"...'.format(model_metafile_name))
    model_metadata_dict = neural_net.read_metafile(model_metafile_name)
    predict_td_to_ts = model_metadata_dict[neural_net.TRAINING_OPTIONS_KEY][
        neural_net.PREDICT_TD_TO_TS_KEY
    ]

    print('Reading SHIPS predictions from: "{0:s}"...'.format(
        ships_prediction_file_name
    ))

    if predict_td_to_ts:
        ships_prediction_dict = ships_prediction_io.read_td_to_ts_file(
            ships_prediction_file_name
        )
    else:
        ships_prediction_dict = ships_prediction_io.read_ri_file(
            ships_prediction_file_name
        )

    cnn_indices, ships_indices = _match_examples(
        cnn_prediction_dict=cnn_prediction_dict,
        ships_prediction_dict=ships_prediction_dict
    )

    if predict_td_to_ts:
        cnn_lead_times_hours = cnn_prediction_dict[prediction_io.LEAD_TIMES_KEY]
        ships_lead_times_hours = (
            ships_prediction_dict[ships_prediction_io.LEAD_TIMES_KEY]
        )
        lead_time_indices = [
            -1 if l not in cnn_lead_times_hours else
            numpy.where(ships_lead_times_hours == l)[0][0]
            for l in cnn_lead_times_hours
        ]

        if use_td_to_ts_lge:
            this_key = ships_prediction_io.FORECAST_LABELS_LGE_KEY
        else:
            this_key = ships_prediction_io.FORECAST_LABELS_LAND_KEY

        ships_prob_matrix_ships_lead_times = (
            ships_prediction_dict[this_key][ships_indices, :].astype(float)
        )
        ships_prob_matrix_ships_lead_times[
            ships_prob_matrix_ships_lead_times < -0.1
        ] = numpy.nan

        # This creates an E-by-L matrix.
        ships_prob_matrix_cnn_lead_times = numpy.transpose(numpy.vstack([
            numpy.full(len(ships_indices), numpy.nan) if l == -1
            else ships_prob_matrix_ships_lead_times[:, l]
            for l in lead_time_indices
        ]))

        # This creates an E-by-K-by-L-by-S matrix.
        ships_prob_matrix_cnn_lead_times = numpy.expand_dims(
            ships_prob_matrix_cnn_lead_times, axis=-2
        )
        ships_prob_matrix_cnn_lead_times = numpy.concatenate((
            1. - ships_prob_matrix_cnn_lead_times,
            ships_prob_matrix_cnn_lead_times
        ), axis=-2)

        ships_prob_matrix_cnn_lead_times = numpy.expand_dims(
            ships_prob_matrix_cnn_lead_times, axis=-1
        )

        d = cnn_prediction_dict
        print('Writing matched SHIPS predictions to: "{0:s}"...'.format(
            output_file_name
        ))

        prediction_io.write_file(
            netcdf_file_name=output_file_name,
            forecast_probability_matrix=ships_prob_matrix_cnn_lead_times,
            target_class_matrix=
            d[prediction_io.TARGET_MATRIX_KEY][cnn_indices, ...],
            cyclone_id_strings=[
                d[prediction_io.CYCLONE_IDS_KEY][k] for k in cnn_indices
            ],
            init_times_unix_sec=d[prediction_io.INIT_TIMES_KEY][cnn_indices],
            storm_latitudes_deg_n=
            d[prediction_io.STORM_LATITUDES_KEY][cnn_indices],
            storm_longitudes_deg_e=
            d[prediction_io.STORM_LONGITUDES_KEY][cnn_indices],
            model_file_name=d[prediction_io.MODEL_FILE_KEY],
            lead_times_hours=d[prediction_io.LEAD_TIMES_KEY],
            quantile_levels=d[prediction_io.QUANTILE_LEVELS_KEY]
        )

        return

    ships_probabilities = (
        ships_prediction_dict[ships_prediction_io.RI_PROBABILITIES_KEY][
            ships_indices, int(use_ri_consensus)
        ]
    ).astype(float)

    ships_probabilities[ships_probabilities < -0.1] = numpy.nan

    # Create an E-by-K-by-L-by-S matrix.
    ships_prob_matrix = numpy.expand_dims(ships_probabilities, axis=-1)
    ships_prob_matrix = numpy.concatenate(
        (1. - ships_prob_matrix, ships_prob_matrix), axis=-1
    )
    ships_prob_matrix = numpy.expand_dims(ships_prob_matrix, axis=-1)
    ships_prob_matrix = numpy.expand_dims(ships_prob_matrix, axis=-1)

    d = cnn_prediction_dict

    print('Writing matched SHIPS predictions to: "{0:s}"...'.format(
        output_file_name
    ))

    prediction_io.write_file(
        netcdf_file_name=output_file_name,
        forecast_probability_matrix=ships_prob_matrix,
        target_class_matrix=
        d[prediction_io.TARGET_MATRIX_KEY][cnn_indices, ...],
        cyclone_id_strings=[
            d[prediction_io.CYCLONE_IDS_KEY][k] for k in cnn_indices
        ],
        init_times_unix_sec=d[prediction_io.INIT_TIMES_KEY][cnn_indices],
        storm_latitudes_deg_n=
        d[prediction_io.STORM_LATITUDES_KEY][cnn_indices],
        storm_longitudes_deg_e=
        d[prediction_io.STORM_LONGITUDES_KEY][cnn_indices],
        model_file_name=d[prediction_io.MODEL_FILE_KEY],
        lead_times_hours=d[prediction_io.LEAD_TIMES_KEY],
        quantile_levels=d[prediction_io.QUANTILE_LEVELS_KEY]
    )


if __name__ == '__main__':
    INPUT_ARG_OBJECT = INPUT_ARG_PARSER.parse_args()

    _run(
        cnn_prediction_file_name=getattr(INPUT_ARG_OBJECT, CNN_FILE_ARG_NAME),
        ships_prediction_file_name=getattr(
            INPUT_ARG_OBJECT, SHIPS_FILE_ARG_NAME
        ),
        use_ri_consensus=bool(
            getattr(INPUT_ARG_OBJECT, USE_RI_CONSENSUS_ARG_NAME)
        ),
        use_td_to_ts_lge=bool(
            getattr(INPUT_ARG_OBJECT, USE_TD_TO_TS_LGE_ARG_NAME)
        ),
        output_file_name=getattr(INPUT_ARG_OBJECT, OUTPUT_FILE_ARG_NAME)
    )
