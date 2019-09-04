import numpy as np
import pandas as pd


class CalculatorBase(object):

    def _verify(self, verbose):
        pass


class Calculator(CalculatorBase):

    def _prepare(self, verbose):
        pass

    def insert_row(self, row):
        pass

    def set_rows(self, rows):
        pass


class Visualizer(Calculator):

    def run(self):
        pass

    def __init__(self, rows=None, **kwargs):
        super(Calculator, self).__init__()
        pass

    def create_html(self, filename="plot.html"):
        pass
