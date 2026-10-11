"""Commercial opportunity: willingness to change now, kept separate from product fit."""
from .signals import KINDS

# Answers recorded after the qualification call (script questions P3, P4 and P6).
QUESTIONS = {
    'change': ('Ha probado o incorporado herramientas en el último año', 25),
    'timing': ('Tiene un motivo para actuar este año', 15),
    'decision': ('Decide la compra y puede aprobar el gasto', 20),
}
SIGNAL_CAP = 40
STATUSES = ('target', 'later', 'pending', 'unwilling')

def signal_points(signals):
    # One entry per kind; unreviewed findings count half until a person confirms them.
    best = {}
    for s in signals:
        weight = KINDS.get(s['kind'], ('', '', 0))[2]
        if not weight or s['review'] == 'rejected' or s.get('recency') != 'recent': continue
        best[s['kind']] = max(best.get(s['kind'], 0), weight if s['review'] == 'confirmed' else weight // 2)
    return min(SIGNAL_CAP, sum(best.values()))

def opportunity(answers, signals):
    answers = answers or {}
    signal = signal_points(signals)
    reasons = [{'field': 'signals', 'label': 'Señales recientes de la gestora', 'points': signal, 'maximum': SIGNAL_CAP, 'answer': None}]
    for key, (label, weight) in QUESTIONS.items():
        reasons.append({'field': key, 'label': label, 'points': weight if answers.get(key) == 'yes' else 0, 'maximum': weight, 'answer': answers.get(key)})
    if 'no' in (answers.get('change'), answers.get('decision')): status = 'unwilling'
    elif answers.get('timing') == 'no': status = 'later'
    elif answers.get('change') == 'yes' and answers.get('decision') == 'yes' and (answers.get('timing') == 'yes' or signal): status = 'target'
    else: status = 'pending'
    return {'opportunity_score': sum(r['points'] for r in reasons), 'opportunity_status': status, 'opportunity_reasons': reasons,
            'qualification': {k: answers.get(k) for k in QUESTIONS} | {k: answers.get(k) for k in ('updated_at', 'author')}}
