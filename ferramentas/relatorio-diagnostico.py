"""Relatório de Diagnóstico | O Analista.
Uso: python3 relatorio.py mensagem.txt saida.pdf [--nota "comentário do André"]
mensagem.txt = o texto que chegou no WhatsApp pelo questionário de oanalista-br.github.io/diagnostico"""
import sys, re, html, datetime, os
from playwright.sync_api import sync_playwright

def ler(txt):
    d = {}
    for l in txt.splitlines():
        if ':' in l and not l.startswith('*'):
            k, v = l.split(':', 1); d[k.strip().rstrip('?')] = v.strip()
    return d

def num(v):
    v = re.sub(r'[^\d,.\-]', '', v or '0').replace('.', '').replace(',', '.')
    try: return float(v)
    except ValueError: return 0.0

R = lambda v: ('-' if v < 0 else '') + 'R$ ' + f'{abs(v):,.0f}'.replace(',', '.')
P = lambda v: f'{v*100:.1f}%'.replace('.', ',')

def analisa(d):
    g = lambda k: num(d.get(k))
    fat, cmv, fix, imp, pro, cx, div, parc = (g('Faturamento médio por mês'), g('Custo da mercadoria ou dos insumos por mês'), g('Despesas fixas por mês'),
        g('Impostos e taxas do cartão por mês'), g('Quanto você tira para você por mês'), g('Quanto a empresa tem em caixa hoje'), g('Dívidas da empresa (total)'), g('Parcela mensal dessas dívidas'))
    mc = fat - cmv - imp; mcp = mc / fat if fat else 0
    op = mc - fix                      # lucro da operação, antes de pagar o dono
    sobra = op - pro - parc            # o que sobra no mês depois de tudo
    saida_mes = fix + pro + parc
    pe = saida_mes / mcp if mcp > 0 else None
    folego = cx / saida_mes * 30 if saida_mes else 0
    pts = {'Sim': 1, 'Mais ou menos': .5, 'Não': 0}
    org = {k: d.get(k, 'Não') for k in ['As contas da empresa são separadas das suas', 'Você anota o que entra e sai, por data',
           'Você sabe quanto lucra em cada produto ou serviço', 'O negócio funciona uma semana sem você', 'Tem clientes que compram todo mês ou contratos']}
    nota_org = sum(pts.get(v, 0) for v in org.values())
    mult = 2 + 0.4 * nota_org
    lucro_ano = (op - pro) * 12        # lucro de verdade: o comprador paga alguém no lugar do dono
    divliq = max(0, div - cx)
    val = (lucro_ano * mult - divliq) if lucro_ano > 0 else 0
    faixa = (max(0, lucro_ano * max(1.5, mult - .5) - divliq), max(0, lucro_ano * (mult + .5) - divliq)) if lucro_ano > 0 else (0, 0)
    pot = max(0, lucro_ano * 4 - divliq) if lucro_ano > 0 else 0
    prob = []
    def add(peso, titulo, texto, acao, projeto): prob.append((peso, titulo, texto, acao, projeto))
    if sobra < 0: add(100, 'O mês fecha no vermelho', f'Depois de pagar o negócio, você e as parcelas, faltam {R(-sobra)} por mês. Esse buraco está sendo coberto pelo caixa, por dívida ou pelo seu bolso.', 'Rever preço e custos antes de qualquer outro passo.', 'Precificação')
    if folego < 30: add(90, 'Caixa curto', f'O caixa de hoje paga cerca de {folego:.0f} dias das saídas fixas do mês. Qualquer mês fraco vira aperto.', 'Montar o fluxo de caixa por data e criar uma reserva da empresa.', 'Caixa sob controle')
    if d.get('Quanto das vendas é a prazo ou no cartão parcelado') in ('Metade', 'Mais da metade') and org['Você anota o que entra e sai, por data'] != 'Sim':
        add(80, 'Venda a prazo sem controle de datas', 'Grande parte das vendas entra aos poucos, e as contas vencem de uma vez. Sem anotar por data, o buraco aparece de surpresa.', 'Lançar entradas e saídas por data (planilha LUCRO) e negociar prazos com fornecedores.', 'Caixa sob controle')
    if fat and parc / fat > .08: add(75, 'Dívida pesando', f'As parcelas levam {P(parc/fat)} do faturamento. É dinheiro que não volta para o negócio.', 'Listar as dívidas pelo juro e renegociar as mais caras primeiro.', 'Caixa sob controle')
    if fat and 0 <= sobra / fat < .05: add(70, 'Margem apertada', f'Sobram só {P(sobra/fat)} do que você vende. Um desconto ou um aumento de custo já zera o lucro.', 'Calcular a margem de cada produto e ajustar o preço dos que dão menos.', 'Precificação')
    if org['Você sabe quanto lucra em cada produto ou serviço'] != 'Sim': add(60, 'Preço no escuro', 'Sem saber o lucro de cada item, é fácil vender muito do que dá pouco (ou até prejuízo).', 'Usar a calculadora de markup e margem (palavra PREÇO) nos 10 itens que mais vendem.', 'Precificação')
    if org['As contas da empresa são separadas das suas'] != 'Sim': add(55, 'Contas misturadas', 'Com o dinheiro da casa e da empresa juntos, não dá para saber o lucro de verdade.', 'Conta PJ só da empresa e pró-labore fixo, num dia fixo.', 'Check-up financeiro')
    if org['O negócio funciona uma semana sem você'] != 'Sim': add(45, 'Tudo depende de você', 'Para quem compra ou para um sócio, um negócio que depende do dono vale bem menos.', 'Escrever o passo a passo das tarefas que só você sabe fazer.', 'Valuation')
    prob.sort(key=lambda x: -x[0])
    if len(prob) < 3: add(10, 'Base boa para crescer', 'Os números básicos estão saudáveis. O próximo passo é crescer sem perder margem.', 'Definir metas de margem e de caixa e acompanhar todo mês.', 'Valuation')
    obj = d.get('Seu objetivo para os próximos 12 meses', '')
    proj = 'Valuation' if obj in ('Vender a empresa', 'Trazer um sócio ou investidor', 'Saber quanto a empresa vale') else prob[0][4]
    return dict(fat=fat, cmv=cmv, fix=fix, imp=imp, pro=pro, cx=cx, div=div, parc=parc, mc=mc, mcp=mcp, op=op, sobra=sobra, pe=pe, folego=folego,
                org=org, mult=mult, lucro_ano=lucro_ano, val=val, faixa=faixa, pot=pot, prob=prob[:3], proj=proj)

PROJ = {'Valuation': 'Avaliação completa do quanto a empresa vale, com cenários e o que fazer para aumentar esse valor.',
        'Precificação': 'Cálculo do custo e da margem de cada produto ou serviço, e a tabela de preços certa para lucrar.',
        'Caixa sob controle': 'Fluxo de caixa montado com você, plano para as dívidas e reserva da empresa.',
        'Check-up financeiro': 'Organização das contas, pró-labore, controles e um plano de 90 dias.'}

def sinal(ok, meio=False): return 'verde' if ok else ('amarelo' if meio else 'vermelho')

def gera(d, a, nota=''):
    nome = html.escape(d.get('Seu nome', 'Empreendedor(a)')); neg = html.escape(d.get('O que você vende', ''))
    hoje = datetime.date.today().strftime('%d/%m/%Y')
    ind = [('Faturamento por mês', R(a['fat']), '', ''),
           ('Margem de contribuição', P(a['mcp']), 'O que sobra de cada venda depois da mercadoria, impostos e taxas.', sinal(a['mcp'] >= .4, a['mcp'] >= .25)),
           ('Lucro da operação', R(a['op']), 'Antes de pagar você e as dívidas.', sinal(a['op'] > a['pro'] + a['parc'], a['op'] > 0)),
           ('Sobra no fim do mês', R(a['sobra']), 'Depois do seu pró-labore e das parcelas.', sinal(a['sobra'] > .05 * a['fat'], a['sobra'] >= 0)),
           ('Ponto de equilíbrio', R(a['pe']) if a['pe'] else 'não calculável', 'Quanto precisa vender por mês para empatar.', sinal(bool(a['pe']) and a['pe'] < .85 * a['fat'], bool(a['pe']) and a['pe'] <= a['fat'])),
           ('Fôlego de caixa', f"{a['folego']:.0f} dias", 'Quanto tempo o caixa de hoje paga as saídas fixas.', sinal(a['folego'] >= 90, a['folego'] >= 30))]
    cards = ''.join(f'<div class="ind {c}"><div class="k">{k}</div><div class="v">{v}</div><div class="e">{e}</div></div>' for k, v, e, c in ind)
    orgs = ''.join(f'<tr><td>{html.escape(k)}?</td><td class="{ {"Sim":"ok","Mais ou menos":"meio"}.get(v,"nao") }">{html.escape(v)}</td></tr>' for k, v in a['org'].items())
    probs = ''.join(f'<div class="prob"><div class="n">{i}</div><div><b>{t}</b><p>{x}</p><p class="acao">O que fazer: {ac}</p></div></div>' for i, (_, t, x, ac, _p) in enumerate(a['prob'], 1))
    val = (f'<div class="valor">{R(a["val"])}</div><p>Faixa provável: {R(a["faixa"][0])} a {R(a["faixa"][1])}. Lucro de verdade do ano ({R(a["lucro_ano"])}) vezes um múltiplo de ' + f'{a["mult"]:.1f}'.replace('.', ',') + 'x' +
           (f', menos a dívida líquida de {R(max(0,a["div"]-a["cx"]))}' if a['div'] > a['cx'] else '') + '.</p>' +
           (f'<p class="ganho">Organizado (múltiplo de 4x), o mesmo lucro valeria {R(a["pot"])}.</p>' if a['pot'] > a['val'] else '')) if a['lucro_ano'] > 0 else \
          '<p>Pagando alguém no seu lugar, hoje o negócio não sobra lucro. Antes de falar em valor, o foco é margem e custo.</p>'
    nota_html = f'<section><h2>Comentário do Analista</h2><p>{html.escape(nota)}</p></section>' if nota else ''
    return f'''<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8"><title>Diagnóstico | {nome}</title>
<link href="https://fonts.googleapis.com/css2?family=Bangers&family=Comic+Neue:wght@400;700&display=swap" rel="stylesheet">
<style>
@page {{ size:A4; margin:14mm 12mm; }}
body {{ font-family:"Comic Neue",sans-serif; color:#1b1b1b; font-size:12.5pt; line-height:1.4; background:#fbf3dc; -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
.topo {{ display:flex; justify-content:space-between; background:#1f2a44; color:#fff; padding:8px 14px; font-weight:700; letter-spacing:.05em; }}
h1 {{ font-family:Bangers,sans-serif; font-weight:400; font-size:34pt; margin:14px 0 4px; background:#f6c945; border:3px solid #1b1b1b; box-shadow:5px 5px 0 #1b1b1b; padding:6px 14px; letter-spacing:.03em; }}
h2 {{ font-family:Bangers,sans-serif; font-weight:400; font-size:20pt; color:#1f2a44; margin:0 0 8px; letter-spacing:.04em; }}
section {{ background:#fff; border:3px solid #1b1b1b; box-shadow:4px 4px 0 #1b1b1b; padding:12px 14px; margin:14px 0; break-inside:avoid; }}
.meta {{ margin:10px 0; }}
.grid {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:10px; }}
.ind {{ border:2px solid #1b1b1b; padding:8px; border-left-width:10px; }}
.ind .k {{ font-weight:700; font-size:10.5pt; }} .ind .v {{ font-family:Bangers,sans-serif; font-size:22pt; letter-spacing:.02em; }} .ind .e {{ font-size:9.5pt; color:#555; }}
.verde {{ border-left-color:#2f8a4c; }} .amarelo {{ border-left-color:#e3a20b; }} .vermelho {{ border-left-color:#d8432e; }}
table {{ width:100%; border-collapse:collapse; }} td {{ padding:5px 4px; border-bottom:1px dashed #bbb; }} td:last-child {{ text-align:right; font-weight:700; }}
.ok {{ color:#2f8a4c; }} .meio {{ color:#b07a00; }} .nao {{ color:#d8432e; }}
.prob {{ display:flex; gap:12px; margin:10px 0; }} .prob .n {{ flex:none; width:34px; height:34px; background:#d8432e; color:#fff; font-family:Bangers,sans-serif; font-size:20pt; display:flex; align-items:center; justify-content:center; border:2px solid #1b1b1b; }}
.prob p {{ margin:3px 0; }} .acao {{ font-weight:700; color:#1f2a44; }}
.valor {{ font-family:Bangers,sans-serif; font-size:36pt; color:#1f2a44; }} .ganho {{ background:#2f8a4c; color:#fff; padding:6px 10px; font-weight:700; }}
.cta {{ background:#f6c945; }}
.aviso {{ font-size:9pt; color:#555; }}
</style></head><body>
<div class="topo"><span>O ANALISTA</span><span>@OANALISTA.BR</span></div>
<h1>Diagnóstico do seu negócio</h1>
<div class="meta"><b>{nome}</b>{' · ' + neg if neg else ''} · {html.escape(d.get('Cidade',''))} · {hoje}</div>
<section><h2>Seus números do mês</h2><div class="grid">{cards}</div></section>
<section><h2>Os 3 pontos que mais pedem atenção</h2>{probs}</section>
<section><h2>Quanto o seu negócio vale hoje</h2>{val}</section>
<section><h2>Como está a organização</h2><table>{orgs}</table></section>
{nota_html}
<section class="cta"><h2>Próximo passo recomendado: {a["proj"]}</h2><p>{PROJ[a["proj"]]}</p><p><b>Quer conversar sobre isso? Responda esta mensagem no WhatsApp: (44) 99974-3738.</b></p></section>
<p class="aviso">Relatório feito a partir dos números que você informou, que são aproximados. Os indicadores e o valor estimado são uma referência inicial para pequenas empresas (múltiplos variam por setor) e não substituem uma análise completa. Conteúdo educacional, não é recomendação de investimento.</p>
</body></html>'''

if __name__ == '__main__':
    txt = open(sys.argv[1], encoding='utf-8').read(); out = sys.argv[2]
    nota = sys.argv[sys.argv.index('--nota') + 1] if '--nota' in sys.argv else ''
    d = ler(txt); a = analisa(d); h = gera(d, a, nota)
    open(out.replace('.pdf', '.html'), 'w').write(h)
    with sync_playwright() as p:
        b = p.chromium.launch(**({'executable_path': '/usr/bin/google-chrome'} if os.path.exists('/usr/bin/google-chrome') else {})); pg = b.new_page()
        pg.set_content(h, wait_until='networkidle'); pg.pdf(path=out, format='A4', print_background=True); b.close()
    print('ok', out, '| sobra', R(a['sobra']), '| valor', R(a['val']), '| projeto', a['proj'])
