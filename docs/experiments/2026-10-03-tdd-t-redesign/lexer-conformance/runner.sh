zzmarker(){ printf ZZHIT >&2; }
[ -n "$BASH_VERSION" ] && export -f zzmarker
n=0
while IFS= read -r line; do
  S=${line//$'\x01'/$'\n'}
  out=$( eval "$S" 2>&1 >/dev/null </dev/null )
  case $out in
    *ZZHIT*) r=HIT;;
    *"syntax error"*|*"unexpected EOF"*|*"unexpected end"*|*"unmatched"*|*"parse error"*|*"bad substitution"*|*"unterminated"*|*"unexpected token"*|*"bad math"*|*"missing"*) r=SYN;;
    *) r=NO;;
  esac
  printf '%s\n' "$r"
done
