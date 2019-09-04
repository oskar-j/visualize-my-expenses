import numpy as np
import pandas as pd


class CalculatorBase(object):

    def _verify(self, verbose) -> bool:
        pass

    def print_to_console(self):
        pass


class Calculator(CalculatorBase):

    def __init__(self):
        self.verbose = False

    def _prepare(self, verbose):
        pass

    def insert_row(self, row):
        pass

    def set_rows(self, rows):
        if rows is None:
            self.rows = list()
        else:
            self.rows = rows
        pass

    def append_rows(self, rows):
        if self.rows is not None:
            self.rows += rows
        else:
            self.set_rows(rows)
