# Colorized ls: BSD ls (macOS) takes -G, GNU ls (Linux) takes --color=auto.
if [[ $OSTYPE == darwin* ]]; then
  alias ls='ls -G'
else
  alias ls='ls --color=auto'
fi

export OMP_DEFAULT_USER=$(logname)
export EDITOR=nano
export PATH="$HOME/.local/bin:$PATH"
# LS_COLORS should influence ls output, and zsh tab completion output.
# di=01;34 means directories should be bold and blue
# ex=01;31 means executables should be bold and red
# su=01;30;41 means setuid files should be bold and black on red
export LS_COLORS="di=01;34:ln=01:36:su=01;30;41:ex=01;31"

# --- Zsh Completion Setup ---
# Add Homebrew's site-functions to the FPATH
if type brew &>/dev/null; then
  FPATH="$(brew --prefix)/share/zsh-completions:${FPATH}"
  FPATH="$(brew --prefix)/share/zsh/site-functions:${FPATH}"
fi

# Add custom user completions to the FPATH
FPATH="$HOME/.zsh/completions:${FPATH}"

# Initialize the completion system
autoload -Uz compinit
compinit

# tab completion shows the menu of possible completions
# "select" means when you tab, depending on # of possible completions:
#  1 possible completion: completes input
#    if there's a shared prefix across all possible completions, it will fill in the prefix
#    if there's under some threshold of possible completions, it will fill in the shared prefix, no options displayed
#    else it will display all options on the first tab, but not take over input. You can continue typing, or press
#      right to accept an autosuggestion. On a second tab, it will highlight the first option, and subsequent tabs
#      will change the highlighted option. Arrow keys will change the selection as well. Enter will accept that option
#      and clear menu.
# "select=#" acts as above, but if the number of displayed options is below the number, subsequent tabs will put
#    the next completion on the line, but will not clear out the options. (You can just tab through the options
#    until you press a non-tab button.) But if there are more options than #, it will go into menu-mode.
# "interactive" alone doesn't appear to do anything.
# "interactive" with a "select[=#]" option works like the select, but when it first shows a menu, it shows
#    'interactive: <input>[]' and blocks further tabs. If you type, it reduces the set of options to those that still
#    fit the updated prefix. If you use arrows, it gets rid of the 'interactive' line, and acts like select from then
#    on. This is pretty inflexible though. You are only extending the prefix, not searching anywhere within options.
# "search" acts similar to "interactive", but in some ways better, and in other ways worse.  Characters you type
#    are checked against any part of the options, not just a continuation of the prefix. It will highlight the first
#    option that matches the new string, but it doesn't ever reduce the set of options using the new search string.
#    Also, hitting enter doesn't accept the highlighted option, it just drops out of search mode, back into menu mode.
#    You have to hit enter a second time to accept the option. I like the search better, but the lack of filtering and
#    the requirement to hit enter twice doesn't feel as good.
zstyle ':completion:*' menu select=5 interactive #search

bindkey -M menuselect '\e' send-break # ESC will leave menu selection without inserting anything.

# try normal completion rules first. If no results, look for things that would match with a small amount of correction
zstyle ':completion:*' completer _complete _approximate

# Case-insensitive matching, partial-word ("cd /u/l/b<TAB> ➜ expands to ➜ cd /usr/local/bin"), and substring completion
zstyle ':completion:*' matcher-list 'm:{a-zA-Z-_}={A-Za-z_-}' 'r:|=*' 'l:|=* r:|=*'
# m:{a-zA-Z-_}={A-Za-z_-} (Case-Insensitive & Interchangeable Characters)
# The m: stands for "match equivalence". It tells Zsh that characters on the left side of the = should be treated
#    interchangeably with characters on the right side.
# a-zA-Z = A-Za-z: This creates standard case-insensitivity. It tells Zsh that if you type a lowercase a, it is allowed
#    to match an uppercase A, and vice versa.

# r:|=* ("Partial-Word" Matching)
# By default, you have to type the prefix of a word to complete it. Partial-word matching allows Zsh to insert hidden
# wildcards * between the characters you type under certain conditions (usually around slashes, dots, hyphens, etc).
# The r:|=* directive effectively means "allow a wildcard on the right side of what I typed."
# In practice, the most famous example of partial-word matching is with file paths. Instead of pressing <TAB> after
# every single directory like this: cd /u<TAB>/l<TAB>/b<TAB>
# You can just type the first letter of each directory, press <TAB> once at the end, and Zsh will expand the whole path:
# cd /u/l/b<TAB> ➜ expands to ➜ cd /usr/local/bin

# l:|=* r:|=* (Substring Matching)
# If neither of the previous rules found a completion, this is the final fallback.
# l: means "allow wildcards on the left" and r: means "allow wildcards on the right".
# By using both, this effectively surrounds your input with wildcards (e.g., *YOUR_INPUT*).

_comp_options+=(globdots) # allow tab completion to include hidden files
setopt GLOB_COMPLETE # hitting tab after something that ends in '*' tab completes within the pattern, instead of
                     # expanding out to be the list of things in the pattern.
setopt LIST_ROWS_FIRST # sorted from left to right, then top to bottom; instead of top to bottom, then left to right.

# Group matches and add styling to descriptions
zstyle ':completion:*' group-name '' # this sorts options by group, under the group description. Else all descriptions
                                     # would be at the top, and all results would be mixed in below
zstyle ':completion:*:*:*:*:matches' group 'yes'
zstyle ':completion:*:*:*:*:options' description 'yes'
zstyle ':completion:*:*:*:*:descriptions' format '%F{green}-- %d --%f'
zstyle ':completion:*:*:*:*:corrections' format '%F{yellow}!- %d (errors: %e) -!%f'
zstyle ':completion:*:*:*:*:messages' format '%F{purple}-- %d --%f'
zstyle ':completion:*:*:*:*:warnings' format '%F{red}-- no matches found --%f'

# Group ordering
zstyle ':completion:*:*:-command-:*:*' group-order alias builtins functions commands

# Caching for completions that support it (improves performance for heavy commands)
zstyle ':completion:*' use-cache on
zstyle ':completion:*' cache-path "$HOME/.zcompcache"

# Colors for completion
zstyle ':completion:*:default' list-colors "${(s.:.)LS_COLORS}" ma=0\;33\;100
# ----------------------------

source $(brew --prefix)/share/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh
source $(brew --prefix)/share/zsh-autosuggestions/zsh-autosuggestions.zsh

# History management
SAVEHIST=100000
HISTSIZE=100000
setopt SHARE_HISTORY
setopt HIST_IGNORE_SPACE
# ----------------------------

# Trigger
eval "$(oh-my-posh init zsh --config ~/.config/oh-my-posh/joshua-yanchar.omp.json)"

# needs to come after oh-my-posh initialization because that defines a placeholder set_poshcontext which would overwrite
# anything we declared before initialization.
function set_poshcontext() {
  sudo -n true >/dev/null 2>&1
  export SUDO_CACHE_ACTIVE=$(( $? == 0 ))
}
