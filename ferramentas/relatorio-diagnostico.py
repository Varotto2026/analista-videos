"""Relatório de Diagnóstico | O Analista.
Uso: python3 relatorio.py mensagem.txt saida.pdf [--nota "comentário do André"]
mensagem.txt = o texto que chegou no WhatsApp pelo questionário de oanalista-br.github.io/diagnostico"""
import sys, re, html, datetime, os
from playwright.sync_api import sync_playwright

def ler(txt):
    d = {}
    for l in txt.splitlines():
        if ':' in l and not l.startswith('*'):
            k, v = l.split(':', 1); d.setdefault(k.strip().rstrip('?'), v.strip())
    d['_txt'] = txt
    return d

def num(v):
    v = re.sub(r'[^\d,.\-]', '', v or '0').replace('.', '').replace(',', '.')
    try: return float(v)
    except ValueError: return 0.0

R = lambda v: ('-' if v < 0 else '') + 'R$ ' + f'{abs(v):,.0f}'.replace(',', '.')
P = lambda v: f'{v*100:.1f}%'.replace('.', ',')
Pc = lambda v: f'{v*100:.0f}%' if abs(v * 100 - round(v * 100)) < 1e-9 else P(v)   # sem casa decimal quando é número redondo

NS = lambda v: 'não sei' in (v or '').lower()
# Médias usadas quando a pessoa marca "Não sei" (referência para pequenas empresas, % do faturamento)
CMV_SETOR = [('Comércio', .55), ('Alimentação', .35), ('Indústria', .45), ('Beleza', .10), ('Serviços', .12), ('Prestador', .05)]
IMP_REGIME = {'MEI': .04, 'Simples Nacional': .09, 'Lucro Presumido': .15, 'Lucro Real': .15}
REP_SETOR = [('Beleza', .40), ('Serviços', .30)]
# Peso de cada informação no resultado: define a confiança do relatório quando a pessoa marca "Não sei"
PESO = {'custo da mercadoria ou dos insumos': 3, 'despesas fixas': 3, 'repasse aos profissionais': 3, 'impostos e taxas do cartão': 2,
        'quanto você tira para você': 2, 'dívidas': 2, 'parcela das dívidas': 1, 'caixa de hoje': 1}

def analisa(d):
    tipo, regime = d.get('Tipo de negócio', ''), d.get('Enquadramento', '')
    est, est_txt, nsab = [], [], []    # campos estimados pela média / como foram estimados / campos sem informação
    def g(k, padrao=None, nome=None, como=None):
        v = d.get(k)
        if not NS(v): return num(v)
        if padrao is None: nsab.append(nome); return 0.0
        est.append(nome); est_txt.append(f'{nome} ({como or ("média de mercado: " + Pc(padrao / fat) + " do faturamento" if fat else "usamos zero")})'); return padrao
    fat = g('Faturamento médio por mês')
    setor = lambda tab, pad: next((x for t, x in tab if tipo.startswith(t)), pad)
    cmv = g('Custo da mercadoria ou dos insumos por mês', fat * setor(CMV_SETOR, .30), 'custo da mercadoria ou dos insumos')
    fix = g('Despesas fixas por mês', fat * .25, 'despesas fixas')
    imp = g('Impostos e taxas do cartão por mês', fat * IMP_REGIME.get(regime, .09), 'impostos e taxas do cartão')
    pro = g('Quanto você tira para você por mês', fat * .08, 'quanto você tira para você')
    cx_ns = NS(d.get('Quanto a empresa tem em caixa hoje')); cx = g('Quanto a empresa tem em caixa hoje', None, 'caixa de hoje')
    div_ns = NS(d.get('Dívidas da empresa (total)')); div = g('Dívidas da empresa (total)', None, 'dívidas')
    parc = g('Parcela mensal dessas dívidas', div / 24, 'parcela das dívidas', 'média de mercado: dívida paga em 24 meses')
    # Repasse aos profissionais (comissão): coluna própria ou a linha [Repasse ...] dentro de "Mais detalhes"
    rv = d.get('Repasse aos profissionais (comissão)') or ''
    m = re.search(r'\[Repasse aos profissionais \(comissão\): *([^\]]*)\]', d.get('_txt', ''))
    if not rv and m: rv = m.group(1)
    if NS(rv): rep_p = setor(REP_SETOR, .30); est.append('repasse aos profissionais'); est_txt.append(f'repasse aos profissionais (média de mercado: {Pc(rep_p)} do faturamento)')
    else: rep_p = min(num(rv), 100) / 100 if rv else 0.0
    rep = fat * rep_p
    mc = fat - cmv - imp - rep; mcp = mc / fat if fat else 0
    op = mc - fix                      # lucro da operação, antes de pagar o dono
    sobra = op - pro - parc            # o que sobra no mês depois de tudo
    saida_mes = fix + pro + parc
    pe = saida_mes / mcp if mcp > 0 else None
    folego = None if cx_ns else (cx / saida_mes * 30 if saida_mes else 0)
    pts = {'Sim': 1, 'Mais ou menos': .5, 'Não': 0}
    org = {k: d.get(k, 'Não') for k in ['As contas da empresa são separadas das suas', 'Você anota o que entra e sai, por data',
           'Você sabe quanto lucra em cada produto ou serviço', 'O negócio funciona uma semana sem você', 'Tem clientes que compram todo mês ou contratos']}
    nota_org = sum(pts.get(v, 0) for v in org.values())
    mult = 2 + 0.4 * nota_org
    lucro_ano = (op - pro) * 12        # lucro de verdade: o comprador paga alguém no lugar do dono
    divliq = max(0, div - cx)
    sem_div = div_ns
    val = (lucro_ano * mult - divliq) if lucro_ano > 0 else 0
    faixa = (max(0, lucro_ano * max(1.5, mult - .5) - divliq), max(0, lucro_ano * (mult + .5) - divliq)) if lucro_ano > 0 else (0, 0)
    pot = max(0, lucro_ano * 4 - divliq) if lucro_ano > 0 else 0
    # Fluxo de caixa descontado (FCD): lucro de verdade projetado por 5 anos + perpetuidade, trazido a valor de hoje
    taxa = .35 - .02 * nota_org        # 35% ao ano (desorganizada) a 25% (organizada): juros de mercado + risco de pequena empresa
    cresc, perp, anos = .05, .035, 5   # crescimento nos 5 anos e na perpetuidade (perto da inflação)
    def fcd(r):
        if lucro_ano <= 0: return None
        fl = [lucro_ano * (1 + cresc) ** t for t in range(1, anos + 1)]
        vp = [f / (1 + r) ** t for t, f in enumerate(fl, 1)]
        vt = fl[-1] * (1 + perp) / (r - perp); vpvt = vt / (1 + r) ** anos
        return dict(fl=fl, vp=vp, vt=vt, vpvt=vpvt, ev=sum(vp) + vpvt, val=max(0, sum(vp) + vpvt - divliq))
    dcf = fcd(taxa); val_mult = val
    if dcf:                            # valor final = média dos dois métodos; faixa cobre os dois (FCD com taxa +-3 pontos)
        val = (val_mult + dcf['val']) / 2
        faixa = (min(faixa[0], fcd(taxa + .03)['val']), max(faixa[1], fcd(taxa - .03)['val']))
    # Confiança: quanto do resultado depende de números que a pessoa não soube informar
    falta = est + nsab; pts = sum(PESO.get(x, 1) for x in falta)
    conf = 'alta' if pts == 0 else ('média' if pts <= 2 else 'baixa')
    abre = {'alta': 0, 'média': .10, 'baixa': .25}[conf]   # faixa mais larga quando falta informação
    faixa = (faixa[0] * (1 - abre), faixa[1] * (1 + abre))
    obs = ' (conta feita com valores estimados)' if conf == 'baixa' else ''
    prob = []
    def add(peso, titulo, texto, acao, projeto): prob.append((peso, titulo, texto, acao, projeto))
    if sobra < 0: add(100, 'O mês fecha no vermelho', f'Depois de pagar o negócio, você e as parcelas, faltam {R(-sobra)} por mês{obs}. Esse buraco está sendo coberto pelo caixa, por dívida ou pelo seu bolso.', 'Rever preço e custos antes de qualquer outro passo.', 'Precificação')
    if cx_ns: add(92, 'Caixa sem controle', 'Você não sabe quanto a empresa tem em caixa hoje. Sem esse número, não dá para saber se o dinheiro aguenta um mês fraco.', 'Conferir o saldo da empresa toda semana e montar o fluxo de caixa por data (planilha LUCRO).', 'Caixa sob controle')
    elif folego < 30: add(90, 'Caixa curto', f'O caixa de hoje paga cerca de {folego:.0f} dias das saídas fixas do mês. Qualquer mês fraco vira aperto.', 'Montar o fluxo de caixa por data e criar uma reserva da empresa.', 'Caixa sob controle')
    if d.get('Quanto das vendas é a prazo ou no cartão parcelado') in ('Metade', 'Mais da metade') and org['Você anota o que entra e sai, por data'] != 'Sim':
        add(80, 'Venda a prazo sem controle de datas', 'Grande parte das vendas entra aos poucos, e as contas vencem de uma vez. Sem anotar por data, o buraco aparece de surpresa.', 'Lançar entradas e saídas por data (planilha LUCRO) e negociar prazos com fornecedores.', 'Caixa sob controle')
    if fat and parc / fat > .08: add(75, 'Dívida pesando', f'As parcelas levam {P(parc/fat)} do faturamento{obs if "parcela das dívidas" in est else ""}. É dinheiro que não volta para o negócio.', 'Listar as dívidas pelo juro e renegociar as mais caras primeiro.', 'Caixa sob controle')
    if fat and 0 <= sobra / fat < .05: add(70, 'Margem apertada', f'Sobram só {P(sobra/fat)} do que você vende{obs}. Um desconto ou um aumento de custo já zera o lucro.', 'Calcular a margem de cada produto e ajustar o preço dos que dão menos.', 'Precificação')
    if org['Você sabe quanto lucra em cada produto ou serviço'] != 'Sim': add(60, 'Preço no escuro', 'Sem saber o lucro de cada item, é fácil vender muito do que dá pouco (ou até prejuízo).', 'Usar a calculadora de markup e margem (palavra PREÇO) nos 10 itens que mais vendem.', 'Precificação')
    if org['As contas da empresa são separadas das suas'] != 'Sim': add(55, 'Contas misturadas', 'Com o dinheiro da casa e da empresa juntos, não dá para saber o lucro de verdade.', 'Conta PJ só da empresa e pró-labore fixo, num dia fixo.', 'Check-up financeiro')
    if org['O negócio funciona uma semana sem você'] != 'Sim': add(45, 'Tudo depende de você', 'Para quem compra ou para um sócio, um negócio que depende do dono vale bem menos.', 'Escrever o passo a passo das tarefas que só você sabe fazer.', 'Valuation')
    faltam = est + [x for x in nsab if x != 'caixa de hoje']
    if len(faltam) >= 2:
        add(85, 'Números no escuro', f'Você não soube informar: {", ".join(faltam)}. Usamos a média de mercado no lugar desses valores, mas o negócio só fica sob controle quando esses números estão na sua mão.', 'Levantar esses valores no extrato do banco, nas notas e na maquininha do último mês.', 'Check-up financeiro')
    prob.sort(key=lambda x: -x[0])
    if len(prob) < 3: add(10, 'Base boa para crescer', ('Pelos números informados e pela média de mercado usada no que faltou, a base parece saudável, mas confirme com os valores reais.' if conf != 'alta' else 'Os números básicos estão saudáveis.') + ' O próximo passo é crescer sem perder margem.', 'Definir metas de margem e de caixa e acompanhar todo mês.', 'Valuation')
    obj = d.get('Seu objetivo para os próximos 12 meses', '')
    proj = 'Valuation' if obj in ('Vender a empresa', 'Trazer um sócio ou investidor', 'Saber quanto a empresa vale') else prob[0][4]
    return dict(conf=conf, falta=falta, est_txt=est_txt, est=est, nsab=nsab, rep=rep, rep_p=rep_p, sem_div=sem_div, fat=fat, cmv=cmv, fix=fix, imp=imp, pro=pro, cx=cx, div=div, parc=parc, mc=mc, mcp=mcp, op=op, sobra=sobra, pe=pe, folego=folego,
                org=org, mult=mult, lucro_ano=lucro_ano, val=val, val_mult=val_mult, dcf=dcf, taxa=taxa, cresc=cresc, perp=perp, divliq=divliq, faixa=faixa, pot=pot, prob=prob[:3], proj=proj)

PROJ = {'Valuation': 'Avaliação completa do quanto a empresa vale, com cenários e o que fazer para aumentar esse valor.',
        'Precificação': 'Cálculo do custo e da margem de cada produto ou serviço, e a tabela de preços certa para lucrar.',
        'Caixa sob controle': 'Fluxo de caixa montado com você, plano para as dívidas e reserva da empresa.',
        'Check-up financeiro': 'Organização das contas, pró-labore, controles e um plano de 90 dias.'}

def sinal(ok, meio=False): return 'verde' if ok else ('amarelo' if meio else 'vermelho')

def gera(d, a, nota=''):
    nome = html.escape(d.get('Seu nome', 'Empreendedor(a)')); neg = html.escape(d.get('O que você vende', ''))
    hoje = datetime.date.today().strftime('%d/%m/%Y')
    ind = [('Faturamento por mês', R(a['fat']), '', ''),
           ('Margem de contribuição', P(a['mcp']), 'O que sobra de cada venda depois da mercadoria, impostos e taxas' + (f' e do repasse de {Pc(a["rep_p"])} aos profissionais.' if a['rep'] else '.'), sinal(a['mcp'] >= .4, a['mcp'] >= .25)),
           ('Lucro da operação', R(a['op']), 'Antes de pagar você e as dívidas.', sinal(a['op'] > a['pro'] + a['parc'], a['op'] > 0)),
           ('Sobra no fim do mês', R(a['sobra']), 'Depois do seu pró-labore e das parcelas.', sinal(a['sobra'] > .05 * a['fat'], a['sobra'] >= 0)),
           ('Ponto de equilíbrio', R(a['pe']) if a['pe'] else 'não calculável', 'Quanto precisa vender por mês para empatar.', sinal(bool(a['pe']) and a['pe'] < .85 * a['fat'], bool(a['pe']) and a['pe'] <= a['fat'])),
           ('Fôlego de caixa', f"{a['folego']:.0f} dias" if a['folego'] is not None else 'não informado', 'Quanto tempo o caixa de hoje paga as saídas fixas.', sinal(a['folego'] is not None and a['folego'] >= 90, a['folego'] is not None and a['folego'] >= 30))]
    dep = {'Margem de contribuição': {'custo da mercadoria ou dos insumos', 'impostos e taxas do cartão', 'repasse aos profissionais'}}
    dep['Lucro da operação'] = dep['Margem de contribuição'] | {'despesas fixas'}
    dep['Sobra no fim do mês'] = dep['Lucro da operação'] | {'quanto você tira para você', 'parcela das dívidas'}
    dep['Ponto de equilíbrio'] = dep['Sobra no fim do mês']
    dep['Fôlego de caixa'] = {'despesas fixas', 'quanto você tira para você', 'parcela das dívidas'}
    ind = [(k, v + ('*' if dep.get(k, set()) & set(a['est']) and not v.startswith('não') else ''), e, c) for k, v, e, c in ind]
    lista = ', '.join(a['falta'])
    aviso_conf = {'alta': '',
        'média': f'<div class="conf media"><b>Resultado aproximado.</b> Você não soube informar: {lista}. Fizemos a análise com o que você passou e, nesses pontos, usamos a média de mercado. Por isso os números abaixo são uma aproximação.</div>',
        'baixa': f'<div class="conf baixa"><b>Atenção: resultado com pouca certeza.</b> Você não soube informar: {lista}. Esses números pesam muito na análise. Fizemos as contas com o que você passou e, no lugar desses valores, usamos a média de mercado. Mas, diante da falta dessas informações, não é possível ter certeza do lucro, do ponto de equilíbrio e do valor da empresa. Leia os resultados como uma estimativa. Se conseguir esses valores, responda no WhatsApp que eu refaço o relatório.</div>'}[a['conf']]
    est_html = ('<p class="est">* ' + (f'Calculado com a média de mercado, porque você marcou "Não sei" em: {", ".join(a["est_txt"])}. ' if a['est'] else '') +
                (f'Sem informação, {"ficou" if len(a["nsab"]) == 1 else "ficaram"} fora das contas: {", ".join(a["nsab"])}. ' if a['nsab'] else '') +
                'Com os números reais, o resultado pode mudar.</p>') if a['est'] or a['nsab'] else ''
    cards = ''.join(f'<div class="ind {c}"><div class="k">{k}</div><div class="v">{v}</div><div class="e">{e}</div></div>' for k, v, e, c in ind)
    orgs = ''.join(f'<tr><td>{html.escape(k)}?</td><td class="{ {"Sim":"ok","Mais ou menos":"meio"}.get(v,"nao") }">{html.escape(v)}</td></tr>' for k, v in a['org'].items())
    probs = ''.join(f'<div class="prob"><div class="n">{i}</div><div><b>{t}</b><p>{x}</p><p class="acao">O que fazer: {ac}</p></div></div>' for i, (_, t, x, ac, _p) in enumerate(a['prob'], 1))
    if a['lucro_ano'] > 0:
        f = a['dcf']; pc = lambda v: f'{v*100:.0f}%'.replace('.', ',') if v*100 == int(v*100) else P(v)
        div_txt = f', menos a dívida líquida de {R(a["divliq"])}' if a['divliq'] > 0 else (', sem descontar dívidas, que você não informou' if a['sem_div'] else '')
        cab = ''.join(f'<th>Ano {t}</th>' for t in range(1, len(f['fl']) + 1)) + '<th>Ano 6 em diante</th><th>Total</th>'
        l1 = ''.join(f'<td>{R(x)}</td>' for x in f['fl']) + f'<td>{R(f["fl"][-1] * (1 + a["perp"]))}/ano</td><td></td>'
        l2 = ''.join(f'<td>{R(x)}</td>' for x in f['vp']) + f'<td>{R(f["vpvt"])}</td><td>{R(f["ev"])}</td>'
        ress = {'alta': '', 'média': '<p class="ress">Calculado em parte com a média de mercado, porque faltaram algumas informações. Por isso a faixa ficou mais larga.</p>',
                'baixa': '<p class="ress">Calculado em parte com a média de mercado, porque faltaram informações. Esse valor é só uma indicação e pode ser bem diferente, para mais ou para menos. A faixa ficou mais larga por isso.</p>'}[a['conf']]
        val = (f'<div class="valor">{R(a["val"])}{"*" if a["conf"] != "alta" else ""}</div>{ress}<p>Faixa provável: {R(a["faixa"][0])} a {R(a["faixa"][1])}. É a média de dois métodos de avaliação:</p>'
               f'<div class="metodos"><div class="met"><div class="k">Múltiplo de lucro</div><div class="v">{R(a["val_mult"])}</div>'
               f'<div class="e">Lucro de verdade do ano ({R(a["lucro_ano"])}) vezes ' + f'{a["mult"]:.1f}'.replace('.', ',') + f'x, o quanto o mercado costuma pagar por empresas parecidas{div_txt}.</div></div>'
               f'<div class="met"><div class="k">Fluxo de caixa descontado</div><div class="v">{R(f["val"])}</div>'
               f'<div class="e">Todo o lucro que a empresa ainda vai gerar, trazido para o valor de hoje{div_txt}.</div></div></div>'
               f'<table class="fcd"><tr><th></th>{cab}</tr><tr><td>Lucro projetado</td>{l1}</tr><tr class="hoje"><td>Valor hoje</td>{l2}</tr></table>'
               f'<p class="nota-fcd">Premissas: lucro crescendo {pc(a["cresc"])} ao ano por 5 anos e {P(a["perp"])} ao ano depois disso, descontado a {pc(a["taxa"])} ao ano '
               f'(juros de mercado mais o risco de uma pequena empresa). Quanto mais organizada a empresa, menor o risco, menor a taxa e maior o valor.</p>' +
               (f'<p class="ganho">Organizado (múltiplo de 4x), o mesmo lucro valeria {R(a["pot"])} pelo múltiplo.</p>' if a['pot'] > a['val_mult'] else ''))
    else:
        val = '<p>Pagando alguém no seu lugar, hoje o negócio não sobra lucro. Sem lucro, nem o múltiplo nem o fluxo de caixa descontado mostram valor. Antes de falar em valor, o foco é margem e custo.</p>'
    np_ = len(a['prob']); tit_prob = 'O ponto que mais pede atenção' if np_ == 1 else f'Os {np_} pontos que mais pedem atenção'
    nota_html = f'<section><h2>Comentário do Analista</h2><p>{html.escape(nota)}</p></section>' if nota else ''
    return f'''<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8"><title>Diagnóstico | {nome}</title>
<link href="https://fonts.googleapis.com/css2?family=Bangers&family=Comic+Neue:wght@400;700&display=swap" rel="stylesheet">
<style>
@page {{ size:A4; margin:12mm 12mm; }}
body {{ font-family:"Comic Neue",sans-serif; color:#1b1b1b; font-size:12.5pt; line-height:1.4; background:#fbf3dc; -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
.topo {{ display:flex; justify-content:space-between; background:#1f2a44; color:#fff; padding:8px 14px; font-weight:700; letter-spacing:.05em; }}
h1 {{ font-family:Bangers,sans-serif; font-weight:400; font-size:34pt; margin:14px 0 4px; background:#f6c945; border:3px solid #1b1b1b; box-shadow:5px 5px 0 #1b1b1b; padding:6px 14px; letter-spacing:.03em; }}
h2 {{ font-family:Bangers,sans-serif; font-weight:400; font-size:20pt; color:#1f2a44; margin:0 0 8px; letter-spacing:.04em; }}
section {{ background:#fff; border:3px solid #1b1b1b; box-shadow:4px 4px 0 #1b1b1b; padding:10px 14px; margin:11px 0; break-inside:avoid; }}
.meta {{ margin:10px 0; }}
.grid {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:10px; }}
.ind {{ border:2px solid #1b1b1b; padding:8px; border-left-width:10px; }}
.ind .k {{ font-weight:700; font-size:10.5pt; }} .ind .v {{ font-family:Bangers,sans-serif; font-size:22pt; letter-spacing:.02em; }} .ind .e {{ font-size:9.5pt; color:#555; }}
.verde {{ border-left-color:#2f8a4c; }} .amarelo {{ border-left-color:#e3a20b; }} .vermelho {{ border-left-color:#d8432e; }}
table {{ width:100%; border-collapse:collapse; }} td {{ padding:3px 4px; border-bottom:1px dashed #bbb; }} td:last-child {{ text-align:right; font-weight:700; }}
.ok {{ color:#2f8a4c; }} .meio {{ color:#b07a00; }} .nao {{ color:#d8432e; }}
.prob {{ display:flex; gap:12px; margin:10px 0; break-inside:avoid; }} section.probs {{ break-inside:auto; }} .prob .n {{ flex:none; width:34px; height:34px; background:#d8432e; color:#fff; font-family:Bangers,sans-serif; font-size:20pt; display:flex; align-items:center; justify-content:center; border:2px solid #1b1b1b; }}
.prob p {{ margin:3px 0; }} .acao {{ font-weight:700; color:#1f2a44; }}
.valor {{ font-family:Bangers,sans-serif; font-size:36pt; color:#1f2a44; }} .ganho {{ background:#2f8a4c; color:#fff; padding:6px 10px; font-weight:700; }}
.cta {{ background:#f6c945; }}
.metodos {{ display:grid; grid-template-columns:1fr 1fr; gap:10px; margin:8px 0; }}
.met {{ border:2px solid #1b1b1b; padding:8px; border-left:10px solid #1f2a44; }} .met .k {{ font-weight:700; font-size:10.5pt; }} .met .v {{ font-family:Bangers,sans-serif; font-size:20pt; letter-spacing:.02em; }} .met .e {{ font-size:9.5pt; color:#555; }}
table.fcd {{ font-size:9pt; margin-top:6px; }} table.fcd th {{ text-align:right; font-size:8.5pt; border-bottom:2px solid #1b1b1b; padding:3px 2px; white-space:nowrap; }} table.fcd td {{ padding:3px 2px; text-align:right; white-space:nowrap; font-weight:400; }} table.fcd td:first-child {{ text-align:left; font-weight:700; }} table.fcd tr.hoje td {{ font-weight:700; }}
.ress {{ font-weight:700; color:#b0341f; margin:2px 0 6px; }}
.nota-fcd {{ font-size:9.5pt; color:#555; }}
.conf {{ border:3px solid #1b1b1b; padding:8px 12px; margin:10px 0 4px; font-size:11pt; }} .conf.baixa {{ background:#f9d3cc; border-left:12px solid #d8432e; }} .conf.media {{ background:#fff4cc; border-left:12px solid #e3a20b; }}
.est {{ font-size:9.5pt; background:#fff4cc; border-left:6px solid #e3a20b; padding:4px 8px; margin:8px 0 0; }}
.aviso {{ font-size:9pt; color:#555; }}
</style></head><body>
<div class="topo"><span>O ANALISTA</span><span>@OANALISTA.BR</span></div>
<h1>Diagnóstico do seu negócio</h1>
<div class="meta"><b>{nome}</b>{' · ' + neg if neg else ''} · {html.escape(d.get('Cidade',''))} · {hoje}</div>
{aviso_conf}
<section><h2>Seus números do mês</h2><div class="grid">{cards}</div>{est_html}</section>
<section class="probs"><h2>{tit_prob}</h2>{probs}</section>
<section><h2>Quanto o seu negócio vale hoje</h2>{val}</section>
<section><h2>Como está a organização</h2><table>{orgs}</table></section>
{nota_html}
<section class="cta"><h2>Próximo passo recomendado: {a["proj"]}</h2><p>{PROJ[a["proj"]]}</p><p><b>Quer conversar sobre isso? Responda esta mensagem no WhatsApp: (44) 99974-3738.</b></p></section>
<p class="aviso">Relatório feito a partir dos números que você informou, que são aproximados. Os indicadores e o valor estimado são uma referência inicial para pequenas empresas (múltiplos e taxas de desconto variam por setor) e não substituem uma análise completa. Conteúdo educacional, não é recomendação de investimento.</p>
</body></html>'''

if __name__ == '__main__':
    txt = open(sys.argv[1], encoding='utf-8').read(); out = sys.argv[2]
    nota = sys.argv[sys.argv.index('--nota') + 1] if '--nota' in sys.argv else ''
    d = ler(txt); a = analisa(d); h = gera(d, a, nota)
    open(out.replace('.pdf', '.html'), 'w').write(h)
    with sync_playwright() as p:
        b = p.chromium.launch(**({'executable_path': '/usr/bin/google-chrome'} if os.path.exists('/usr/bin/google-chrome') else {})); pg = b.new_page()
        pg.set_content(h, wait_until='networkidle'); pg.pdf(path=out, format='A4', print_background=True); b.close()
    print('ok', out, '| confiança', a['conf'], ('(' + ', '.join(a['falta']) + ')') if a['falta'] else '', '| sobra', R(a['sobra']), '| valor', R(a['val']), '(múltiplo', R(a['val_mult']), '| FCD', (R(a['dcf']['val']) if a['dcf'] else '-') + ')', '| projeto', a['proj'])
