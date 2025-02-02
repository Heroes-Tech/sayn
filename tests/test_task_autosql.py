from contextlib import contextmanager

import pytest
from sayn.tasks.autosql import AutoSqlTask

from . import inside_dir, simulate_task, tables_with_data, validate_table, clear_tables


@contextmanager
def autosql_task(tmp_path, used_objects, target_db, sql, data=None, **kwargs):
    """Creates an autosql task and drops the tables/views created after it's done"""
    fs = {"sql/test.sql": sql} if sql is not None else dict()
    with inside_dir(tmp_path, fs):
        task = simulate_task(AutoSqlTask, used_objects, target_db=target_db, **kwargs)
        if data is not None:
            with tables_with_data(task.connections["target_db"], data):
                yield task
        else:
            yield task
        if hasattr(task, "table"):
            clear_tables(
                task.connections["target_db"],
                [
                    f"{task.schema +'.' if task.schema else ''}{task.table}",
                    f"{task.tmp_schema +'.' if task.tmp_schema else ''}sayn_tmp_{task.table}",
                ],
            )


def test_autosql_task_table(tmp_path, target_db):
    used_objects = dict()
    with autosql_task(tmp_path, used_objects, target_db, "SELECT 1 AS x") as task:
        result = task.config(
            file_name="test.sql",
            materialisation="table",
            destination={"table": "test_autosql_task"},
        )
        assert result.is_ok or result is None

        task.connections["target_db"]._introspect(used_objects["target_db"])
        result = task.setup()
        assert result.is_ok or result is None

        result = task.run()
        assert result.is_ok or result is None
        assert validate_table(task.default_db, "test_autosql_task", [{"x": 1}])


def test_autosql_task_view(tmp_path, target_db):
    used_objects = dict()
    with autosql_task(tmp_path, used_objects, target_db, "SELECT 1 AS x") as task:
        assert task.config(
            file_name="test.sql",
            materialisation="view",
            destination={"table": "test_autosql_task"},
        ).is_ok

        task.connections["target_db"]._introspect(used_objects["target_db"])

        assert task.setup().is_ok

        assert task.run().is_ok
        assert validate_table(
            task.default_db,
            "test_autosql_task",
            [{"x": 1}],
        )


def test_autosql_task_incremental(tmp_path, target_db):
    used_objects = dict()
    with autosql_task(
        tmp_path,
        used_objects,
        target_db,
        "SELECT * FROM source_table WHERE updated_at >= 2 OR updated_at IS NULL",
        {
            "source_table": [
                {"id": 1, "updated_at": 1, "name": "x"},
                {"id": 2, "updated_at": 2, "name": "y1"},
                {"id": 3, "updated_at": None, "name": "z"},
            ],
            "test_autosql_task": [
                {"id": 1, "updated_at": 1, "name": "x"},
                {"id": 2, "updated_at": None, "name": "y"},
            ],
        },
    ) as task:
        assert task.config(
            file_name="test.sql",
            materialisation="incremental",
            destination={"table": "test_autosql_task"},
            delete_key="id",
        ).is_ok

        task.connections["target_db"]._introspect(used_objects["target_db"])
        assert task.setup().is_ok

        assert task.run().is_ok
        assert validate_table(
            task.default_db,
            "test_autosql_task",
            [
                {"id": 1, "updated_at": 1, "name": "x"},
                {"id": 2, "updated_at": 2, "name": "y1"},
                {"id": 3, "updated_at": None, "name": "z"},
            ],
        )


def test_autosql_task_compile(tmp_path, target_db):
    used_objects = dict()
    with autosql_task(
        tmp_path,
        used_objects,
        target_db,
        "SELECT 1 AS x",
        run_arguments={"command": "compile"},
    ) as task:
        assert task.config(
            file_name="test.sql",
            materialisation="table",
            destination={"table": "test_autosql_task"},
        ).is_ok

        task.connections["target_db"]._introspect(used_objects["target_db"])
        assert task.setup().is_ok

        assert task.compile().is_ok


def test_autosql_task_param(tmp_path, target_db):
    used_objects = dict()
    with autosql_task(
        tmp_path,
        used_objects,
        target_db,
        "SELECT {{number}} AS x",
        task_params={"number": 1},
    ) as task:
        assert task.config(
            file_name="test.sql",
            materialisation="table",
            destination={"table": "test_autosql_task"},
        ).is_ok

        task.connections["target_db"]._introspect(used_objects["target_db"])
        assert task.setup().is_ok

        assert task.run().is_ok
        assert validate_table(
            task.default_db,
            "test_autosql_task",
            [{"x": 1}],
        )


def test_autosql_task_config_error1(tmp_path, target_db):
    used_objects = dict()
    with autosql_task(tmp_path, used_objects, target_db, "SELECT 1 AS x") as task:
        assert task.config(
            file_nam="test.sql",
            materialisation="table",
            destination={"table": "test_autosql_task"},
        ).is_err


def test_autosql_task_config_error2(tmp_path, target_db):
    used_objects = dict()
    with autosql_task(tmp_path, used_objects, target_db, "SELECT 1 AS x") as task:
        assert task.config(
            file_name="test.sql",
            materialisation="wrong",
            destination={"table": "test_autosql_task"},
        ).is_err


def test_autosql_task_config_error3(tmp_path, target_db):
    """Tests missing parameters for jinja compilation"""
    used_objects = dict()
    with autosql_task(
        tmp_path,
        used_objects,
        target_db,
        "SELECT {{number}} AS x",
    ) as task:
        with pytest.raises(Exception):
            task.config(
                file_name="test.sql",
                materialisation="table",
                destination={"table": "test_autosql_task"},
            )


def test_autosql_task_run_error(tmp_path, target_db):
    """Tests failure with erratic sql"""
    used_objects = dict()
    with autosql_task(
        tmp_path,
        used_objects,
        target_db,
        "SELECT * FROM non_existing_table",
    ) as task:
        assert task.config(
            file_name="test.sql",
            materialisation="table",
            destination={"table": "test_autosql_task"},
        ).is_ok

        task.connections["target_db"]._introspect(used_objects["target_db"])
        assert task.setup().is_ok

        assert task.run().is_err


# Destination tests


def test_autosql_task_table_db_dst(tmp_path, target_db):
    """Test autosql with db destination set"""
    used_objects = dict()
    with autosql_task(tmp_path, used_objects, target_db, "SELECT 1 AS x") as task:
        assert task.config(
            file_name="test.sql",
            materialisation="table",
            destination={"db": "target_db", "table": "test_autosql_task"},
        ).is_ok

        task.connections["target_db"]._introspect(used_objects["target_db"])
        assert task.setup().is_ok

        assert task.run().is_ok
        assert validate_table(
            task.target_db,
            "test_autosql_task",
            [{"x": 1}],
        )


def test_autosql_task_table_wrong_db_dst(tmp_path, target_db):
    """Test autosql with db destination set but does not exist in connections"""
    used_objects = dict()
    with autosql_task(tmp_path, used_objects, target_db, "SELECT 1 AS x") as task:
        assert task.config(
            file_name="test.sql",
            materialisation="table",
            destination={"db": "wrong_dst", "table": "test_autosql_task"},
        ).is_err


# DDL tests


@pytest.mark.target_dbs(["sqlite"])
def test_autosql_task_run_ddl_columns(tmp_path, target_db):
    used_objects = dict()
    with autosql_task(tmp_path, used_objects, target_db, "SELECT 1 AS x") as task:
        assert task.config(
            file_name="test.sql",
            materialisation="table",
            destination={"table": "test_autosql_task"},
            columns=[{"name": "x", "type": "integer"}],
        ).is_ok

        task.connections["target_db"]._introspect(used_objects["target_db"])
        assert task.setup().is_ok

        assert task.run().is_ok
        # test the pk has indeed been set
        # pk_info = task.default_db.read_data(
        #     "PRAGMA table_info(test_autosql_task)")
        # assert pk_info[0]["pk"] == 1


# @pytest.mark.target_dbs(["sqlite", "mysql", "postgresql"])
# def test_autosql_task_run_indexes_pk01(tmp_path, target_db):
#     """Test indexes with the primary key only returns error on SQLite
#     this is because SQLite requires primary keys to be defined in create table statement
#     so columns definition is needed
#     """
#     with autosql_task(tmp_path, target_db, "SELECT 1 AS x") as task:
#         assert task.setup(
#             file_name="test.sql",
#             materialisation="table",
#             destination={"table": "test_autosql_task"},
#             ddl={"indexes": [{"primary_key": "x"}]},
#         ).is_err


# @pytest.mark.target_dbs(["sqlite", "mysql", "postgresql"])
# def test_autosql_task_run_indexes_pk02(tmp_path, target_db):
#     with autosql_task(tmp_path, target_db, "SELECT 1 AS x") as task:
#         assert task.setup(
#             file_name="test.sql",
#             materialisation="table",
#             destination={"table": "test_autosql_task"},
#             columns=["x"],
#             table_properties=["indexes": [{"primary_key": "x"}]],
#         ).is_err
#
#
# @pytest.mark.target_dbs(["sqlite", "mysql", "postgresql"])
# def test_autosql_task_ddl_diff_pk_err(tmp_path, target_db):
#     """Test autosql task set with different pks in indexes and columns setup error"""
#     with autosql_task(
#         tmp_path,
#         target_db,
#         "SELECT CAST(1 AS INTEGER) AS y, CAST(1 AS TEXT) AS x",
#     ) as task:
#         assert task.setup(
#             file_name="test.sql",
#             materialisation="table",
#             destination={"table": "test_autosql_task"},
#             ddl={
#                 "columns": [
#                     {"name": "y", "type": "int"},
#                     {"name": "x", "type": "text", "primary": True},
#                 ],
#                 # "indexes": {"primary_key": {"columns": ["y"]}},
#             },
#         ).is_err
#
#
@pytest.mark.target_dbs(["sqlite", "postgresql", "mysql", "redshift"])
def test_autosql_task_run_ddl_diff_col_order(tmp_path, target_db):
    """Test that autosql with ddl columns creates a table with order similar to ddl definition"""
    used_objects = dict()
    with autosql_task(
        tmp_path,
        used_objects,
        target_db,
        "SELECT 1 AS y, '1' AS x",
    ) as task:
        assert task.config(
            file_name="test.sql",
            materialisation="table",
            destination={"table": "test_autosql_task"},
            columns=[
                {"name": "x", "type": "text"},
                {"name": "y", "type": "int"},
            ],
        ).is_ok

        task.connections["target_db"]._introspect(used_objects["target_db"])
        assert task.setup().is_ok

        assert task.run().is_ok
        assert validate_table(
            task.default_db,
            "test_autosql_task",
            [{"x": "1", "y": 1}],
        )


#
#


@pytest.mark.target_dbs(["bigquery"])
def test_autosql_task_run_ddl_diff_col_order_bq(tmp_path, target_db):
    """Test that autosql with ddl columns creates a table with order similar to ddl definition"""
    used_objects = dict()
    with autosql_task(
        tmp_path,
        used_objects,
        target_db,
        "SELECT 1 AS y, '1' AS x",
    ) as task:
        assert task.config(
            file_name="test.sql",
            materialisation="table",
            destination={"table": "test_autosql_task"},
            ddl=[
                {"name": "x", "type": "string"},
                {"name": "y", "type": "int64"},
            ],
        ).is_ok

        task.connections["target_db"]._introspect(used_objects["target_db"])
        assert task.setup().is_ok

        assert task.run().is_ok
        assert validate_table(
            task.default_db,
            "test_autosql_task",
            [{"x": "1", "y": 1}],
        )


# Testing schemas: this code expects 2 schemas in the database: test and test2


@pytest.mark.target_dbs(["bigquery", "mysql", "postgresql", "redshift", "snowflake"])
def test_autosql_schemas01(tmp_path, target_db):
    """Autosql task with schema specified"""
    used_objects = dict()
    with autosql_task(
        tmp_path,
        used_objects,
        target_db,
        "SELECT 1 AS y, '1' AS x",
    ) as task:
        assert task.config(
            file_name="test.sql",
            materialisation="table",
            destination={"schema": "test2", "table": "test_autosql_task"},
        ).is_ok

        task.connections["target_db"]._introspect(used_objects["target_db"])
        assert task.setup().is_ok

        assert task.run().is_ok
        assert validate_table(
            task.default_db,
            "test2.test_autosql_task",
            [{"x": "1", "y": 1}],
        )


@pytest.mark.target_dbs(["sqlite"])
def test_autosql_schemas_error01(tmp_path, target_db):
    """Autosql task with schema specified with failure as sqlite doesn't support schemas"""
    used_objects = dict()
    with autosql_task(
        tmp_path,
        used_objects,
        target_db,
        "SELECT 1 AS y, '1' AS x",
    ) as task:
        assert task.config(
            file_name="test.sql",
            materialisation="table",
            destination={"schema": "test2", "table": "test_autosql_task"},
        ).is_err


@pytest.mark.target_dbs(["bigquery", "mysql", "postgresql", "redshift", "snowflake"])
def test_autosql_schemas02(tmp_path, target_db):
    """Autosql task with temporary schema and schema specified"""
    used_objects = dict()
    with autosql_task(
        tmp_path,
        used_objects,
        target_db,
        "SELECT 1 AS y, '1' AS x",
    ) as task:
        assert task.config(
            file_name="test.sql",
            materialisation="table",
            destination={
                "tmp_schema": "test2",
                "schema": "test",
                "table": "test_autosql_task",
            },
        ).is_ok

        task.connections["target_db"]._introspect(used_objects["target_db"])
        assert task.setup().is_ok

        assert task.run().is_ok
        assert validate_table(
            task.default_db,
            "test.test_autosql_task",
            [{"x": "1", "y": 1}],
        )


@pytest.mark.target_dbs(["sqlite"])
def test_autosql_schemas_error02(tmp_path, target_db):
    """Autosql task with temporary schema and schema specified with failure"""
    used_objects = dict()
    with autosql_task(
        tmp_path,
        used_objects,
        target_db,
        "SELECT 1 AS y, '1' AS x",
    ) as task:
        assert task.config(
            file_name="test.sql",
            materialisation="table",
            destination={
                "tmp_schema": "test2",
                "schema": "test",
                "table": "test_autosql_task",
            },
        ).is_err


# AutoSqlTask Testing


def test_autosql_test_names(tmp_path, target_db):
    used_objects = dict()
    with autosql_task(
        tmp_path,
        used_objects,
        target_db,
        "SELECT 1 AS x",
        run_arguments={"command": "test"},
    ) as task:
        assert task.config(
            file_name="test.sql",
            materialisation="table",
            destination={"table": "test_autosql_task"},
            columns=[{"name": "x", "tests": ["unique", "not_null"]}],
        ).is_ok

        task.connections["target_db"]._introspect(used_objects["target_db"])
        assert task.setup().is_ok
        assert task.run().is_ok
        assert task.test().is_ok


def test_autosql_test_lists(tmp_path, target_db):
    used_objects = dict()
    with autosql_task(
        tmp_path,
        used_objects,
        target_db,
        "SELECT 1 AS x",
        run_arguments={"command": "test"},
    ) as task:
        assert task.config(
            file_name="test.sql",
            materialisation="table",
            destination={"table": "test_autosql_task"},
            columns=[
                {"name": "x", "tests": [{"name": "unique"}, {"name": "not_null"}]}
            ],
            table_properties={},
            post_hook=[],
        ).is_ok

        task.connections["target_db"]._introspect(used_objects["target_db"])
        assert task.setup().is_ok
        assert task.run().is_ok
        assert task.test().is_ok


def test_autosql_test_values(tmp_path, target_db):
    used_objects = dict()
    with autosql_task(
        tmp_path,
        used_objects,
        target_db,
        "SELECT '1' AS x",
        run_arguments={"command": "test"},
    ) as task:
        assert task.config(
            file_name="test.sql",
            materialisation="table",
            destination={"table": "test_autosql_task"},
            columns=[
                {
                    "name": "x",
                    "tests": [
                        {"name": "unique"},
                        {"name": "not_null"},
                        {"name": "allowed_values", "allowed_values": ["1"]},
                    ],
                }
            ],
        ).is_ok

        task.connections["target_db"]._introspect(used_objects["target_db"])
        assert task.setup().is_ok
        assert task.run().is_ok
        assert task.test().is_ok
