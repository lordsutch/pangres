# +
"""
Read docstring of main class Executor
"""
import pandas as pd
from sqlalchemy.engine.base import Connection, Engine
from sqlalchemy.engine.cursor import LegacyCursorResult
from typing import Generator, Union

# local imports
from pangres.helpers import PandasSpecialEngine
from pangres.transaction import TransactionHandler
# -

# # Local helpers

Connectable = Union[Connection, Engine]


# # Class Executor

class Executor:
    """
    Executes SQL setups (creating table, postgresql schema, columns, ...) and then the actual upsert operations
    for pangres.

    Due to the necessity of having `yield` statements in the same scope as pangres' transaction contexts
    (when this is not the case, the context closes before the generator can yield anything)
    I made this class to avoid as much repetition as possible (setup method -> execute|execute_yield).

    We will then import this class in the `core` module and call the appropriate method (execute|execute_yield)
    depending on the parameters.

    See `pangres.core.upsert` for a description of the parameters.
    """

    def __init__(self, df:pd.DataFrame, table_name:str, schema:Union[str, None],
                 create_schema:bool, create_table:bool,
                 add_new_columns:bool, adapt_dtype_of_empty_db_columns:bool,
                 dtype:Union[dict, None]):
        self.df = df
        self.schema = schema
        self.table_name = table_name
        self.dtype = dtype
        self.create_schema = create_schema
        self.create_table = create_table
        self.add_new_columns = add_new_columns
        self.adapt_dtype_of_empty_db_columns = adapt_dtype_of_empty_db_columns

    def _setup_objects(self, pse:PandasSpecialEngine):
        """
        Handles optional pre-upsert operations:
        1. creating the PostgreSQL schema
        2. creating the table
        3. adding missing columns
        4. altering columns data types (if needed) when these columns are
           empty in the db but not in the df
        """
        # create schema if not exists
        # IMPORTANT! `pse.schema` and not `schema`
        # -> With postgres None will be set to `public`
        if self.create_schema and pse.schema is not None:
            pse.create_schema_if_not_exists()

        # create table if not exists
        if self.create_table:
            pse.create_table_if_not_exists()

        # change dtype of empty columns in db
        if self.adapt_dtype_of_empty_db_columns and pse.table_exists():
            pse.adapt_dtype_of_empty_db_columns()

        # add new columns from frame
        if self.add_new_columns and pse.table_exists():
            pse.add_new_columns()

    def execute(self, connectable:Connectable, if_row_exists:str, chunksize:int) -> None:
        """
        Handles the actual upsert operation.
        """
        with TransactionHandler(connectable=connectable) as trans:
            # setup
            pse = PandasSpecialEngine(connection=trans.connection, df=self.df,
                                      table_name=self.table_name, schema=self.schema,
                                      dtype=self.dtype)
            self._setup_objects(pse=pse)

            # upsert
            if len(self.df) == 0:
                return
            pse.upsert(if_row_exists=if_row_exists, chunksize=chunksize)

    def execute_yield(self, connectable:Connectable, if_row_exists:str,
                      chunksize:int) -> Generator[LegacyCursorResult, None, None]:
        """
        Same as `execute` but for each chunk upserted yields a
        `sqlalchemy.engine.cursor.LegacyCursorResult` object with which
        we can for instance retrieve the number of updated rows
        """
        with TransactionHandler(connectable=connectable) as trans:

            # setup
            pse = PandasSpecialEngine(connection=trans.connection, df=self.df,
                                      table_name=self.table_name, schema=self.schema,
                                      dtype=self.dtype)
            self._setup_objects(pse=pse)

            # upsert
            # make sure to return an empty generator in case of an empty DataFrame
            # for consistent data types (thanks to https://stackoverflow.com/a/13243870 !)
            if len(self.df) == 0:
                return
                yield
            for result in pse.upsert_yield(if_row_exists=if_row_exists, chunksize=chunksize):
                yield result
