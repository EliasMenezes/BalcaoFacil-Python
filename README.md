# Balcão Fácil (Python + SQLite)

Servidor local de frente de caixa e estoque, com vários usuários em tempo real. A interface (`public/index.html`) continua a mesma.

- Rodar direto (sem instalar): `python server.py` (abre em http://localhost:8080). Dados: `%LOCALAPPDATA%\BalcaoFacil\data` (Windows) ou `~/.local/share/balcaofacil`. Para mudar: variável `BALCAO_DATA`.
- **Primeiro acesso:** o navegador pede para criar o administrador (só no computador do servidor). Não há senha pré-definida.
- Comandos: `balcaofacil adduser NOME SENHA perfil1,perfil2`, `balcaofacil vendor` (recursos offline; também baixa sozinho na 1ª execução com internet), `balcaofacil atalho` (cria o atalho "Balcão Fácil" na Área de Trabalho).
- **Gerar só o executável (um arquivo):** `build_windows.bat` no Windows (gera `dist\balcaofacil.exe`) e `./build_linux.sh` no Linux (gera `dist/balcaofacil`). Cada um precisa ser gerado no próprio sistema. No GitHub, envie esta pasta (branch `main`) e baixe os dois em **Actions > executaveis > Artifacts**. `installer.iss` (Inno Setup) é opcional, se quiser um Setup.exe.
- Se havia dados da versão Node.js em `data/db.json` na pasta de dados, eles são importados sozinhos na primeira execução.

## Usuários e perfis (Configurações > Usuários e perfis, só Administrador)
Cada usuário pode ter **mais de um perfil** (as permissões se somam), sempre conferidas no servidor:
- **Caixa:** vende (F3), gera orçamento (F4) e recebe.
- **Vendedor:** monta orçamentos (F4) e consulta estoque; não finaliza venda nem efetiva orçamento.
- **Estoquista:** cadastra/edita produtos e vendedores, ajusta estoque e lança NF-e (também vende).
- **Financeiro:** Dashboard, Boletos, Compras e Despesas.
- **Administrador:** tudo, mais usuários, impressora e dados da empresa.
Todos podem trocar a própria senha (Configurações > Minha senha). Requisições, trocas e entregas são de todos os perfis.

## Entrada por NF-e (Produtos > Importar NF-e (XML))
Aceita vários XMLs de NF-e de compra. Cada item é reconhecido pelo código do fornecedor (aprendido nas entradas anteriores) ou pelo EAN; o que não for reconhecido vira produto novo, com **margem personalizável** (por nota e por item) para calcular o preço de venda. Há fator de conversão (ex.: caixa com 12), opção de recalcular o preço dos existentes, bloqueio de nota duplicada pela chave de 44 dígitos e registro das entradas (data, usuário, fornecedor, total). Não valida a assinatura digital do XML.

## Requisição de material, Troca de produtos e Entregas (abas novas)
Seguem os modelos enviados (campos, status, filtros por texto/data/status, ordenação, impressão e CSV) e usam o mesmo banco e o tempo real do sistema.
- **Integração:** o código do produto vem do cadastro (mostra o estoque disponível e avisa "sem estoque"); o Nº do orçamento/venda da entrega vem do Histórico (mostra cliente e total), e cada linha do Histórico tem o botão **Entrega**.
- **Permissões:** todos os perfis criam e editam; só quem tem Estoquista, Financeiro ou Administrador exclui.

## Impressão térmica ESC/POS (Configurações > Impressora térmica)
- **Rede:** informe o IP e a porta (padrão 9100). **USB:** o servidor envia ao driver instalado (Windows: nome da impressora no Windows, ou COMx; Linux/macOS: nome no CUPS ou /dev/usb/lpX).
- **Modelos:** perfis Epson TM-T20/T88, Elgin i7/i8/i9, Bematech MP-4200 TH, Daruma DR800, Tanca TP-650, Sweda SI-300, Control iD Print iD e genéricas de 80 e 58 mm. Ajuste colunas, tabela de caracteres (acentos) e guilhotina, e confirme com a **Página de teste**.
- A impressora fica ligada ao computador do **servidor** (USB) ou na rede. Se a impressão direta falhar, o sistema avisa e abre a impressão do navegador.

## Financeiro (abas Dashboard, Boletos, Compras e Despesas) — só Administrador e Financeiro
Inspirado no app Tio Patinhas (despesas por categoria, despesa fixa recorrente, alertas de vencimento em 5 dias, extrato e exportação).
- **Boletos:** fornecedor, documento, valor, vencimento, linha digitável, situação (Em aberto, Vencido automático, Pago, Cancelado) e botão de pagar. Filtros, ordenação, impressão e CSV.
- **Compras:** registro por fornecedor/NF-e/forma de pagamento. Ao lançar uma **NF-e**, o sistema cria a compra e os **boletos das duplicatas** da nota (opção na tela de conferência).
- **Despesas:** categoria, valor e marca de **despesa fixa**; o botão "Gerar fixas do mês" copia as fixas do mês anterior que ainda não foram lançadas.
- **Dashboard:** vendas brutas e recebidas (do Histórico; fiado vira "a receber"), taxas estimadas de débito/crédito/PIX (percentuais editáveis, guardados neste navegador), despesas, compras, resultado do período, vendas por forma de pagamento, despesas por categoria e alerta de boletos vencidos ou a vencer. Os boletos não entram no resultado, para não contar a mesma compra duas vezes.
