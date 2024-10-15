import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

from student_onboard_batch_service.wf.onboarding.onboarding_wf import OnboardingWfImpl

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

from datetime import datetime

from airflow import DAG
from airflow.operators.dummy import DummyOperator
from airflow.operators.python import PythonOperator

from student_onboard_batch_service.common.dtos import OnboardStudentReqCtx, OnboardStudentRespCtx
from student_onboard_batch_service.wf.staging_data.staging_data_reader_wf import StagingDataReaderWfImpl

default_args_value = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': datetime(2024, 10, 12),
    'retries': 1,
}


def create_dag(default_args=None, dag_id: str = "Main_DAG", dag_description: str = "Main DAG for onboarding students",
               schedule_interval: str = "@daily", excel_file_distributed: bool = False, deployment_mode: str = "local"):
    if default_args is None:
        default_args = default_args_value

    # Define the function that will be called by the PythonOperator
    if default_args is None:
        default_args = default_args_value

    def read_student_data_from_staging_datazone(staging_path=None, staging_path_provided=None, **kwargs):

        req_ctx = OnboardStudentReqCtx()
        resp_ctx = OnboardStudentRespCtx()

        req_ctx.excel_file_distributed = excel_file_distributed

        # Determine which path to use based on the staging_path_provided flag
        if staging_path_provided and staging_path:
            req_ctx.staging_path = staging_path

        StagingDataReaderWfImpl().execute(req_ctx, resp_ctx)

        if deployment_mode == "local":
            # Push both contexts to XCom
            ti = kwargs['ti']
            ti.xcom_push(key='req_ctx', value=req_ctx.to_json())
            ti.xcom_push(key='resp_ctx', value=resp_ctx.to_json())

    def trigger_bp_dag(**kwargs):
        # Logic to trigger the BP_DAG for each student
        print("Triggering BP_DAG for each student...")

        if deployment_mode == "local":
            ti = kwargs['ti']
            # Pull the contexts from XCom
            req_ctx_json = ti.xcom_pull(task_ids='read_student_data_from_stg_datazone', key='req_ctx')
            resp_ctx_json = ti.xcom_pull(task_ids='read_student_data_from_stg_datazone', key='resp_ctx')

            req_ctx = OnboardStudentReqCtx.from_json(req_ctx_json)
            resp_ctx = OnboardStudentRespCtx.from_json(resp_ctx_json)

        else:
            req_ctx = OnboardStudentReqCtx()
            resp_ctx = OnboardStudentRespCtx()

        OnboardingWfImpl().execute(req_ctx, resp_ctx)

    with DAG(dag_id,
             default_args=default_args,
             description=dag_description,
             schedule_interval=schedule_interval,  # Change the schedule as needed
             catchup=False) as dag:
        # Dummy task to start the workflow
        start = DummyOperator(task_id='start')

        # Task to read student data with parameters for the path and flag
        read_student_data_from_staging_datazone = PythonOperator(
            task_id='read_student_data_from_stg_datazone',
            python_callable=read_student_data_from_staging_datazone,
            op_kwargs={
                'staging_path': '{{ dag_run.conf.get("staging_path", "") }}',
                # Get the staging path from DAG input params, default to None
                'staging_path_provided': '{{ dag_run.conf.get("staging_path_provided", "false") }}'
                # Get the boolean flag, default to None
            },
            provide_context=True
        )

        # Task to trigger the BP_DAG
        trigger_bp = PythonOperator(
            task_id='trigger_bp_dag',
            python_callable=trigger_bp_dag,
            provide_context=True
        )

        end = DummyOperator(task_id='end')

        # Set the task dependencies
        start >> read_student_data_from_staging_datazone >> trigger_bp >> end
