from vme.data_store import Calculator


class Visualizer(Calculator):

    def run(self):
        pass

    def __init__(self, rows=None, currency='USD', **kwargs):
        super(Calculator, self).__init__()
        # set rest of arguments
        self.set_rows(rows)
        self.currency = currency
        # optionally - enable verbosing
        if 'verbose' in kwargs:
            self.verbose = kwargs['verbose']

    def create_html(self, filename="plot.html"):
        # user wishes to generate a file with Sankey plot in an html file
        is_clean = self._verify(verbose=self.verbose)
        # verify first if the data is sanitized
        if is_clean:
            # start the actual plot generation
            pass
        else:
            raise Exception('Data has bad structure - are some of your elements loose?')

    def show_plot(self):
        pass
