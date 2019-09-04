import numpy as np
import pandas as pd


class CalculatorBase(object):

    def _verify(self, verbose):
        pass

    def print_to_console(self):
        pass


class Calculator(CalculatorBase):

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


class Visualizer(Calculator):

    def run(self):
        pass

    def __init__(self, rows=None, currency='USD', **kwargs):
        super(Calculator, self).__init__()
        self.set_rows(rows)
        self.currency = currency

    def create_html(self, filename="plot.html"):
        pass
