'''
    Debugging function that allows running an AI model locally
    (i.e., without the Celery routine). This still requires an
    instance of AIDE that is set up properly, as well as a pro-
    ject containing images (and optionally annotations) to ser-
    ve as a basis.

    Usage:
        python debug/test_model_local.py [project] [mode]

    With:
        - "project": shortname of the project to be used for
          testing
        - "mode": one of {'train', 'inference', 'TODO'}

    2020-24 Benjamin Kellenberger
'''

import os
import argparse
from typing import Optional

from constants.version import AIDE_VERSION
from util import helpers
from util.configDef import Config
from modules import REGISTERED_MODULES
from modules.Database.app import Database
from modules.AIDEAdmin.app import AdminMiddleware
from modules.AIController.backend.functional import AIControllerWorker
from modules.AIWorker.app import AIWorker
from modules.AIWorker.backend.fileserver import FileServer
from modules.AIWorker.backend.worker.functional import __load_model_state, __load_metadata



# check if environment variables are set properly
assert 'AIDE_CONFIG_PATH' in os.environ and os.path.isfile(os.environ['AIDE_CONFIG_PATH']), \
    'ERROR: environment variable "AIDE_CONFIG_PATH" is not set.'
if not 'AIDE_MODULES' in os.environ:
    os.environ['AIDE_MODULES'] = 'LabelUI'
elif not 'labelui' in os.environ['AIDE_MODULES'].lower():
    # required for checking file server version
    os.environ['AIDE_MODULES'] += ',LabelUI'



def test_model_locally(project: str,
                       run_train: bool=False,
                       run_inference: bool=True,
                       update_model: bool=True,
                       model_library_override: Optional[str]=None,
                       model_settings_override: Optional[str]=None) -> None:
    '''
        Load a model and perform a test train and/or inference run with an existing project.
    '''
    # initialize required modules
    config = Config()
    db_connector = Database(config)
    file_server = FileServer(config).get_secure_instance(project)
    aiw = AIWorker(config, db_connector, True)
    aicw = AIControllerWorker(config, None)

    # check if AIDE file server is reachable
    admin = AdminMiddleware(config, db_connector)
    conn_details = admin.getServiceDetails(True, False)
    fs_version = conn_details['FileServer']['aide_version']
    if not isinstance(fs_version, str):
        # no file server running
        raise Exception('''ERROR: AIDE file server is not running, but required for running models.
                           Make sure to launch it prior to running this script.''')
    if fs_version != AIDE_VERSION:
        print(f'''WARNING: the AIDE version of File Server instance ({fs_version})
                  differs from this one ({AIDE_VERSION}).''')

    # get model trainer instance and settings
    query_str = '''
        SELECT ai_model_library, ai_model_settings FROM aide_admin.project
        WHERE shortname = %s;
    '''
    result = db_connector.execute(query_str, (project,), 1)
    if result is None or len(result) == 0:
        raise Exception(f'Project "{project}" could not be found in this installation of AIDE.')

    model_library = result[0]['ai_model_library']
    model_settings = result[0]['ai_model_settings']

    custom_settings_specified = False
    if isinstance(model_settings_override, str) and len(model_settings_override) > 0:
        # settings override specified
        if model_settings_override.lower() == 'none':
            model_settings_override = None
            custom_settings_specified = True
        elif not os.path.isfile(model_settings_override):
            print(f'''WARNING: model settings override provided, but file cannot be found
                      ("{model_settings_override}").
                      Falling back to project default ("{model_settings}").''')
        else:
            model_settings = model_settings_override
            custom_settings_specified = True

    if isinstance(model_library_override, str) and len(model_library_override) > 0:
        # library override specified; try to import it
        try:
            model_class = helpers.get_class_executable(model_library_override)
            if model_class is None:
                raise ValueError(f'Invalid model class override "{model_library_override}".')
            model_library = model_library_override

            # re-check if current model settings are compatible; warn and set to None if not
            if model_library != result[0]['ai_model_library'] and not custom_settings_specified:
                # project model settings are not compatible with provided model
                print('''WARNING: custom model library specified differs from the one currently set
                         in project. Model settings will be set to None.''')
                model_settings = None

        except Exception as exc:
            print(f'''WARNING: model library override provided ("{model_library_override}"), but
                      could not be imported (message: {exc}).
                      Falling back to project default ("{model_library}").''')

    # initialize instance
    print(f'Using model library "{model_library}".')
    model_trainer = aiw._init_model_instance(project, model_library, model_settings)

    try:
        #TODO: load latest unless override is specified?
        state_dict, _, model_origin_id, _ = __load_model_state(project,
                                                               model_library,
                                                               db_connector)
    except Exception:
        state_dict = None
        model_origin_id = None

    # helper functions
    def update_state_fun(state, message, done=None, total=None):
        print(message, end='')
        if done is not None and total is not None:
            print(f': {done}/{total}')
        else:
            print('')

    # launch task(s)
    if run_train:
        data = aicw.get_training_images(
            project=project,
            maxNumImages=512)
        data = __load_metadata(project, db_connector, data[0], True, model_origin_id)

        if update_model:
            state_dict = model_trainer.update_model(state_dict,
                                                    data,
                                                    update_state_fun)

        result = model_trainer.train(state_dict, data, update_state_fun)
        if result is None:
            raise Exception('''Training function must return an object (trained model state)
                               to be stored in the database.''')

    if run_inference:
        data = aicw.get_inference_images(
            project=project,
            maxNumImages=512)
        data = __load_metadata(project, db_connector, data[0], False, model_origin_id)

        if update_model:
            state_dict = model_trainer.update_model(state_dict, data, update_state_fun)

        result = model_trainer.inference(state_dict, data, update_state_fun)
        #TODO: check result for validity



if __name__ == '__main__':

    # parse arguments
    parser = argparse.ArgumentParser(description='AIDE local model tester')
    parser.add_argument('--project', type=str, required=True,
                        help='Project shortname to draw sample data from.')
    parser.add_argument('--train', type=int, required=False,
                        default=0,
                        help='Set to 1 to run training cycle (default: 0).')
    parser.add_argument('--inference', type=int, required=False,
                        default=1,
                        help='Set to 0 to disable running inference cycle (default: 1).')
    parser.add_argument('--update-model', type=int, default=1,
                        help='''Set to 1 (default) to perform a model update step prior to training
                                or inference. This is required to e.g. adapt the model to new label
                                classes in the project.''')
    parser.add_argument('--model-library', type=str, required=False,
                        help='''Optional AI model library override.
                                Provide a dot-separated Pythonimport path here.''')
    parser.add_argument('--model-settings', type=str, required=False,
                        help='''Optional AI model settings override (absolute or relative path to
                                settings file, or else "none" to not use any predefined
                                settings).''')
    args = parser.parse_args()

    do_train, do_inference = bool(args.train), bool(args.inference)
    assert do_train or do_inference, 'ERROR: either "--train" or "--inference" must be set to 1.'

    test_model_locally(args.project,
                       do_train,
                       do_inference,
                       bool(args.update_model),
                       args.model_library,
                       args.model_settings)
