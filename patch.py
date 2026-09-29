import os

with open('main_controller.py', 'r', encoding='utf-8') as f:
    text = f.read()

target = '''                for aid, st in self._amb_state.items():
                    amb_snapshots[aid] = {'''

replacement = '''                for aid, st in self._amb_state.items():
                    target_pos = None
                    try:
                        t_edge = self.net.getEdge(st["target"])
                        target_pos = t_edge.getShape()[-1]
                    except Exception:
                        pass
                    amb_snapshots[aid] = {
                        "target_position": target_pos,'''

text = text.replace(target, replacement)

with open('main_controller.py', 'w', encoding='utf-8') as f:
    f.write(text)
print('Done!')
