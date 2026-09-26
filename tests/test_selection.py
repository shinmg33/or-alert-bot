import threading
import unittest
from or_alert.monitor import Monitor
from or_alert.windows import Window, GuardError


class FakeDesktop:
    def __init__(self, names):
        self.names=names
        self.index=0
        self.actions=[]
    def select(self,kind,rect,index):
        self.actions.append(kind)
        self.index=index
    def select_next(self,kind,rect):
        self.actions.append(kind)
        self.index=min(self.index+1,len(self.names)-1)
    def capture(self): return self.names[self.index]


class NoWait:
    def wait(self,_): return False
    def is_set(self): return False


class SelectionTest(unittest.TestCase):
    def monitor(self,names):
        monitor=Monitor(Window(0,'fake','fake'), {'interval':30,'departments':[{'name':'외과'}],
                        'rects':{'department':[1,1,20,20]}},NoWait(),lambda *args:None)
        monitor.desktop=FakeDesktop(names)
        monitor.text=lambda image,kind:image
        return monitor

    def test_selects_by_name_without_user_index(self):
        m=self.monitor(['전체','산부인과','외과'])
        m.select_named('department','외과')
        self.assertEqual(m.desktop.index,2)
        self.assertEqual(set(m.desktop.actions),{'department'})

    def test_end_of_list_stops_without_query(self):
        m=self.monitor(['전체','산부인과'])
        with self.assertRaises(GuardError): m.select_named('department','외과')
        self.assertNotIn('query',m.desktop.actions)
