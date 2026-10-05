import random, itertools, json
M = "zzmarker"
rnd = random.Random(20261004)
cases = {}   # string -> family
def add(s, fam):
    if M in s and "\x01" not in s and s not in cases and len(s) < 400:
        cases[s] = fam

# ---- structured wrappers: each maps inner text -> text (marker inside inner)
def esc_bt(s): return s.replace("`", "\\`")
W = {
 "sq":      lambda x: f"echo '{x}'",
 "dq":      lambda x: f'echo "{x}"',
 "ansic":   lambda x: f"echo $'{x}'",
 "dqloc":   lambda x: f'echo $"{x}"',
 "subst":   lambda x: f"echo $({x})",
 "bt":      lambda x: f"echo `{x}`",
 "dq_subst":lambda x: f'echo "$({x})"',
 "dq_bt":   lambda x: f'echo "`{x}`"',
 "arith":   lambda x: f"echo $(({x}))",
 "arith_s": lambda x: f"echo $(( $({x}) ))",
 "param":   lambda x: f"echo ${{v:-{x}}}",
 "dq_param":lambda x: f'echo "${{v:-{x}}}"',
 "param_sub":lambda x: f"echo ${{v:-$({x})}}",
 "comment": lambda x: f"echo a # {x}",
 "comment_mid": lambda x: f"echo a#{x}",
 "comment_nl": lambda x: f"# {x}\necho a",
 "hash_word": lambda x: f"echo #{x}",
 "contin":  lambda x: f"echo a \\\n{x}",
 "contin_in": lambda x: f"echo a\\\n{x}",
 "herestr": lambda x: f"cat <<< {x}",
 "herestr_q": lambda x: f"cat <<< '{x}'",
 "herestr_dq": lambda x: f'cat <<< "{x}"',
 "herestr_sub": lambda x: f"cat <<< $({x})",
 "heredoc_q": lambda x: f"cat <<'E'\n{x}\nE",
 "heredoc_u": lambda x: f"cat <<E\n{x}\nE",
 "heredoc_dq": lambda x: f'cat <<"E"\n{x}\nE',
 "heredoc_bs": lambda x: f"cat <<\\E\n{x}\nE",
 "heredoc_usub": lambda x: f"cat <<E\n$({x})\nE",
 "heredoc_ubt": lambda x: f"cat <<E\n`{x}`\nE",
 "heredoc_dash": lambda x: f"cat <<-E\n\t{x}\n\tE",
 "heredoc_then": lambda x: f"cat <<'E'\nfoo\nE\n{x}",
 "case_pat": lambda x: f"case a in {x}) echo hi;; esac",
 "case_body": lambda x: f"case a in a) {x};; esac",
 "case_word": lambda x: f"case {x} in a) :;; esac",
 "case_psub": lambda x: f"case a in $({x})) :;; esac",
 "bs_escape": lambda x: f"echo \\{x}",
 "bs_semi": lambda x: f"echo a\;{x}",
 "bs_sq":   lambda x: f"echo \\'{x}\\'",
 "bs_dq":   lambda x: f'echo \\"{x}\\"',
 "odd_sq":  lambda x: f"echo '{x}",
 "odd_dq":  lambda x: f'echo "{x}',
 "odd_sq2": lambda x: f"echo ''{x}'",
 "odd_dq2": lambda x: f'echo ""{x}"',
 "adj_q":   lambda x: f"echo 'a'\"b\"{x}",
 "adj_q2":  lambda x: f"echo 'a'{x}'b'",
 "adj_q3":  lambda x: f"echo \"a\"'{x}'\"b\"",
 "seq":     lambda x: f"echo a; {x}",
 "and":     lambda x: f"echo a && {x}",
 "pipe":    lambda x: f"echo a | {x}",
 "paren":   lambda x: f"( {x} )",
 "brace":   lambda x: f"{{ {x}; }}",
 "ifthen":  lambda x: f"if true; then {x}; fi",
 "bg":      lambda x: f"{x} &",
 "plain":   lambda x: x,
 "dq_sq_sub": lambda x: f"""echo "$(echo '{x}')\"""",
 "dq_sub_sq": lambda x: f"""echo "$(echo ')' {x})\"""",
 "sub_dq_paren": lambda x: f'echo $(echo ")" ; {x})',
 "sub_sq_paren": lambda x: f"echo $(echo ')' ; {x})",
 "sub_sq_open": lambda x: f"echo $(echo '(' ; {x})",
 "dq_sub_dq_sq": lambda x: f"""echo "$(echo "'" ; {x})\"""",
 "dq_sub_sq_dsub": lambda x: f"""echo "$(echo '$(' ; {x})\"""",
 "sub_sq_dollar": lambda x: f"echo $(echo '$(' ; {x})",
 "sub_bt_in": lambda x: f"echo $(echo `echo a`; {x})",
 "sub_case_close": lambda x: f"echo $(case a in a) {x};; esac)",
 "sub_comment": lambda x: f"echo $(echo a # )\n{x})",
 "sub_comment2": lambda x: f"echo $(# )\n{x})",
 "sub_dq_bt": lambda x: f'echo $(echo "`echo a`"; {x})',
 "bt_sq": lambda x: f"echo `echo '`'; {x}`",
 "bt_dq": lambda x: f'echo `echo "`"; {x}`',
 "bt_bs": lambda x: f"echo `echo \\`a\\`; {x}`",
 "dq_bt_bs": lambda x: f'echo "`echo \\"a\\"; {x}`"',
 "dollar_sq_esc": lambda x: f"echo $'\\'' {x}",
 "dollar_sq_esc2": lambda x: f"echo $'\\'{x}'",
 "dollar_sq_in_dq": lambda x: f"""echo "$'" {x} "'\"""",
 "dollar_dq_in_sq": lambda x: f"""echo '$"' {x} '"'""",
 "dollar_paren_sq": lambda x: f"echo '$(' {x} ')'",
 "dollar_paren_dq": lambda x: f'echo "$(" {x} ")"',
 "var_sq_in_dq_param": lambda x: f"""echo "${{v:-'}}" {x} "'\"""",
 "arith_paren": lambda x: f"echo $(( (1) + $({x}) ))",
 "arith_dparen": lambda x: f"(( 1 + 1 )); {x}",
 "subshell_arith": lambda x: f"echo $( (echo a); {x} )",
 "sub_arith_ambig": lambda x: f"echo $((echo a); {x})",
 "func_def": lambda x: f"f() {{ {x}; }}; f",
 "for_loop": lambda x: f"for i in a; do {x}; done",
 "while_loop": lambda x: f"while {x}; do break; done",
 "eval_q": lambda x: f"eval '{x}'",
 "eval_dq": lambda x: f'eval "{x}"',
 "bash_c": lambda x: f"bash -c '{x}'",
 "alias_like": lambda x: f"echo a ; \\{x}",
 "quoted_head_sq": lambda x: f"'{x}'",
 "quoted_head_dq": lambda x: f'"{x}"',
 "quoted_head_split": lambda x: f"zz''marker",
 "quoted_head_split2": lambda x: f'zz""marker',
 "quoted_head_bs": lambda x: f"zz\\marker",
 "assign_prefix": lambda x: f"v=1 {x}",
 "assign_sub": lambda x: f"v=$({x})",
 "assign_bt": lambda x: f"v=`{x}`",
 "assign_dq": lambda x: f'v="$({x})"',
 "redir_in_sub": lambda x: f"echo $({x} </dev/null)",
 "negate": lambda x: f"! {x}",
 "time_w": lambda x: f"time {x}",
 "command_w": lambda x: f"command {x}",
 "builtin_w": lambda x: f"builtin {x}",
}
LEAF = [M, f"{M} a", f"echo a; {M}", f"echo {M}", f"printf %s {M}", f"cat zzabsent {M}", f": {M}", f"true && {M}", f"echo '{M}'", f'echo "{M}"', f"echo a; echo {M}"]
names = list(W)
# depth 1 exhaustive: every wrapper x every leaf
for n in names:
    for l in LEAF:
        add(W[n](l), "d1:"+n)
# depth 2 exhaustive over wrappers x wrappers x leaf
for a in names:
    for b in names:
        for l in LEAF[:4]:
            add(W[a](W[b](l)), "d2:"+a)
# depth 3 random (fixed seed)
for _ in range(90000):
    a,b,c = (rnd.choice(names) for _ in range(3))
    add(W[a](W[b](W[c](rnd.choice(LEAF)))), "d3:"+a)
# subst-only deep mixes (nesting up to 3, mixed $() and backtick, dq/sq inserted)
SUBW = ["subst","bt","dq_subst","dq_bt","param_sub","sub_dq_paren","sub_sq_paren","sub_sq_dollar","dq_sub_sq","sub_bt_in","assign_sub","redir_in_sub","herestr_sub"]
for _ in range(40000):
    k = rnd.randint(1,3); s = rnd.choice(LEAF)
    for __ in range(k): s = W[rnd.choice(SUBW)](s)
    add(s, "nest-subst:"+str(k))

# token soup
TOK = [M, " ", "'", '"', "$(", ")", "`", "\\", "#", "$'", '$"', "${v:-", "}", "$((", "))", ";", "\n", "<<E", "E", "<<<", "'E'",
       "echo", "case a in", "a)", ";;", "esac", "(", "\\\n", "&&", "|", "$", "\\'", "<<'E'", "<<-E", "printf", ":", "cat zzabsent", "{", "$(("]
TOKS = TOK
def soup(tl):
    return "".join(tl).replace("\n", "\n")
# exhaustive up to length 4 over a smaller alphabet containing the marker
for L in range(1,5):
    for tl in itertools.product(TOK, repeat=L):
        if M in tl: add("".join(tl), "soup-exh:"+str(L))
# random soup len 3..14
for _ in range(120000):
    L = rnd.randint(4,14)
    tl = [rnd.choice(TOK) for _ in range(L)]
    if rnd.random() < .9: tl.insert(rnd.randrange(len(tl)+1), M)
    add("".join(tl), "soup-rnd")
# random soup around valid skeletons: wrap with random quote noise
NOISE = ["'", '"', "`", "\\", "$(", ")", "#", "$'", "${v:-", "}"]
for _ in range(40000):
    s = W[rnd.choice(names)](rnd.choice(LEAF))
    for __ in range(rnd.randint(1,3)):
        p = rnd.randrange(len(s)+1); s = s[:p]+rnd.choice(NOISE)+s[p:]
    add(s, "mutated")
print(len(cases))
with open("cases.jsonl","w") as f:
    for s,fam in cases.items(): f.write(json.dumps([s,fam])+"\n")
