from vme import Visualizer
from collections import namedtuple

Expense = namedtuple('Expense', ['category', 'label', 'amount', 'currency'])

my_expenses = []

v = Visualizer(rows=my_expenses, currency='PLN')
v.print_to_console()
