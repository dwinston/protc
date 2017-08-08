#!/usr/bin/env python3.6

import os
import re
import ast
from collections import Counter
from IPython import embed
from pyontutils.hierarchies import creatTree
from pyontutils.utils import makeGraph, makePrefixes, async_getter, noneMembers, allMembers, anyMembers
from pyontutils.scigraph_client import Vocabulary
import parsing
import parsing_parsec
from scibot.hypothesis import HypothesisAnnotation
from desc.prof import profile_me

try:
    from misc.debug import TDB
    tdb=TDB()
    printD=tdb.printD
    #printFuncDict=tdb.printFuncDict
    #tdbOff=tdb.tdbOff
except ImportError:
    print('WARNING: you do not have tgbugs misc on this system')
    printD = print

sgv = Vocabulary(cache=True)
RFU = 'protc:references-for-use'
__script_folder__ = os.path.dirname(os.path.realpath(__file__))

error_output = []

# utility

def get_hypothesis_local(uri):
    if 'hypothesis-local' in uri:
        return os.path.splitext(os.path.basename(uri))[0]

def hypothesis_local(hln):
    return 'http://hypothesis-local.olympiangods.org/' + hln + '.pdf'

def url_doi(doi):
    return 'https://doi.org/' + doi

def url_pmid(pmid):
    return 'https://www.ncbi.nlm.nih.gov/pubmed/' + pmid

def addReplies(annos):
    for anno in annos:
        _addParent(anno, annos)

def addParent(anno):
    _addParent(anno, annos)

def _addParent(anno, annos):
    return  # short circuit
    if anno.type == 'reply':
        #print(anno.references)
        for parent_id in anno.references:
            parent = _getAnnoById(parent_id, annos)
            if parent is None:
                continue
            anno.parent = parent
            if not hasattr(parent, 'replies'):
                parent.replies = []
            elif anno not in parent.replies:
                parent.replies.append(anno)
        if not hasattr(anno, 'parent'):
            print(f'Parent deleted for {anno.id} {anno.text} {sorted(anno.tags)} {anno.references}')

#
# docs

def readTagDocs():
    with open(f'{__script_folder__}/../protc-tags.rkt', 'rt') as f:
        text = f.read()
    success, docs, rest = parsing.tag_docs(text)
    tag_lookup = {tag:doc for _, tag, doc in docs}
    return tag_lookup

def addDocLinks(base_url, doc):
    prefix = base_url + '/'
    return re.sub(r'`((?:protc|mo):[^\s]+)`', rf'[\1]({prefix}\1)', doc)

# stats

def citation_tree(annos):
    p = RFU
    trips = []
    for anno in annos:
        hl = get_hypothesis_local(anno.uri)
        if hl:
            s = hl
            if p in anno.tags and 'TODO' not in anno.tags:
                if 'no access' in anno.text:
                    continue  # there are some cases where TODO is missing
                t = anno.text.strip()
                o = get_hypothesis_local(t)
                o = o if o else t
                trips.append((p, s, o))

    return trips

def papers(annos):
    idents = {}
    def add_tag_text(hl, anno, tag):
        if tag in anno.tags:
            idents[hl][tag] = anno.text.strip()

    for anno in annos:
        hl = get_hypothesis_local(anno.uri)
        if hl:
            if hl not in idents:
                idents[hl] = {}
            #print(hl)
            #print(anno.exact)
            #print(anno.tags)
            #print(anno.text)
            #print(anno.user)
            #print('---------------------')
            add_tag_text(hl, anno, 'DOI:')
            add_tag_text(hl, anno, 'protc:parent-doi')
            add_tag_text(hl, anno, 'PMID:')

    return idents

def statistics(annos):
    stats = {}
    for anno in annos:
        hl = str(get_hypothesis_local(anno.uri))
        if hl not in stats:
            stats[hl] = 0
        stats[hl] += 1
    return stats

def tagdefs(annos):
    tags = Counter()
    for anno in annos:
        for tag in anno.tags:
            tags[tag] += 1
    return dict(tags)

def idFromShareLink(link):  # XXX warning this will break
    if 'hyp.is' in link:
        id_ = link.split('/')[3]
        return id_

def shareLinkFromId(id_):
    return 'https://hyp.is/' + id_

def splitLines(text):
    for line in text.split('\n'):
        yield line

def inputRefs(annos):
    for anno in annos:
        if anyMembers(anno.tags, 'protc:input', 'protc:*measure', 'protc:symbolic-measure'):
            for line in splitLines(anno.text):
                if line:
                    id_ = idFromShareLink(line)
                    if id_:
                        yield id_

def getAnnoById(id_):
    return _getAnnoById(id_, annos)

def _getAnnoById(id_, annos):  # ah the taint of global
    try:
        return [a for a in annos if a.id == id_][0]
    except IndexError as e:
        print('could not find', id_, shareLinkFromId(id_))
        return None


# HypothesisAnnotation class customized to deal with replacing
#  exact, text, and tags based on its replies
#  also for augmenting the annotation with distinct fields
#  using annotation-text:exact or something like that... (currently using PROTCUR:annotation-exact which is super akward)
#  eg annotation-text:children to say exactly what the fields are when there needs to be more than one
#  it is possible to figure most of them out from their content but not always

class Hybrid:  # a better HypothesisAnnotation
    control_tags = 'annotation-correction', 'annotation-tags:replace', 'annotation-tags:add', 'annotation-tags:delete' 
    prefix_skip_tags = 'PROTCUR:', 'annotation-'
    text_tags = ('annotation-text:exact',
                 'annotation-text:text',
                 'annotation-text:value',
                 'annotation-text:children',
                 'annotation-correction')
    children_tags = 'annotation-children:delete',
    prefix_ast = 'protc:',
    objects = {}  # TODO updates
    _replies = {}
    reprReplies = True
    _embedded = False

    @classmethod
    def byId(cls, id_):
        try:
            return next(v for v in cls.objects.values()).getObjectById(id_)
        except StopIteration as e:
            raise Warning(f'{cls.__name__}.objects has not been populated with annotations yet!') from e

    def __new__(cls, anno, annos):
        try: 
            self = cls.objects[anno.id]
            if self._text == anno.text and self._tags == anno.tags:
                #printD(f'{self.id} already exists')
                return self
            else:
                #printD(f'{self.id} already exists but something has changed')
                self.__init__(anno, annos)  # just updated the underlying refs no worries
                return self
        except KeyError:
            #printD(f'{anno.id} doesnt exist')
            return super().__new__(cls)
            
    def __init__(self, anno, annos):
        self.annos = annos
        self.id = anno.id  # hardset this to prevent shenanigans
        self.objects[self.id] = self
        self._anno = anno
        self.parent  # populate self._replies before the recursive call
        self.replies
        #if self.replies:
            #print(self.replies)
        list(self.children)  # populate annotation links from the text field to catch issues early
        #if self.id not in self._replies:
            #self._replies[self.id] = set()  # This is bad becuase it means we don't trigger a search

    @property
    def _type(self): return self._anno.type
    @property
    def _exact(self): return self._anno.exact
    @property
    def _text(self): return self._anno.text
    @property
    def _tags(self): return self._anno.tags
    @property
    def references(self): return self._anno.references


    def getAnnoById(self, id_):
        try:
            return [a for a in self.annos if a.id == id_][0]
        except IndexError as e:
            print('could not find', id_, shareLinkFromId(id_))
            return None

    def getObjectById(self, id_):
        try:
            return self.objects[id_]
        except KeyError as e:
            anno = self.getAnnoById(id_)
            if anno is None:
                self.objects[id_] = None
                #print('Problem in', self.shareLink)  # must come after self.objects[id_] = None else RecursionError
                print('Problem in', self.shareLink, f"{self.__class__.__name__}.byId('{self.id}')")
                return None
            else:
                h = self.__class__(anno, self.annos)
                return h

    def _fix_implied_input(self):
        if ': ' in self.text and 'hyp.is' in self.text:
            value_children_text = self.text.split(':', 1)[1]
            value, children_text = value_children_text.split('\n', 1)
            return value.strip(), children_text.strip()
        else:
            return '', ''

    @property
    def isAstNode(self):
        return (noneMembers(self._tags, *self.control_tags)
                and all(noneMembers(tag, *self.prefix_skip_tags) for tag in self.tags)
                and any(anyMembers(tag, *self.prefix_ast) for tag in self.tags))

    @property
    def shareLink(self):
        if self.parent is not None:
            return self.parent.shareLink
        else:
            return shareLinkFromId(self.id)

    @property
    def parent(self):
        if not self.references:
            return None
        else:
            for parent_id in self.references[::-1]:  # go backward to get the direct parent first, slower for shareLink but ok
                parent = self.getObjectById(parent_id)
                if parent is not None:
                    if parent.id not in self._replies:
                        self._replies[parent.id] = set()
                    self._replies[parent.id].add(self)
                    return parent
                else:
                    printD('Replies Issues')

    @property
    def replies(self):
        # for the record, the naieve implementation of this
        # looping over annos everytime is 3 orders of magnitude slower
        try:
            return self._replies[self.id]  # we use self.id here instead of self to avoid recursion on __eq__
        except KeyError:
            self._replies[self.id] = set()
            for anno in [a for a in self.annos if self.id in a.references]:
                # super slow? think again alternate implementations are even slower
                # and induce all sorts of hair raising recursion issues :/
                self.__class__(anno, self.annos)
            return self._replies[self.id]

    @property
    def exact(self):
        # FIXME last one wins for multiple corrections? vs first?
        for reply in self.replies:
            correction = reply.text_correction('exact')
            if correction:  # None and ''
                return correction
        return self._exact

    @property
    def text(self):
        for reply in self.replies:
            correction = reply.text_correction('text')
            if correction is not None:
                return correction
            correction = reply.text_correction('annotation-correction')
            if correction is not None:
                return correction

        if self._text.startswith('SKIP'):
            return ''

        return self._text

    @property
    def value(self):
        for reply in self.replies:
            correction = reply.text_correction('value')
            if correction:
                return correction

        if anyMembers(self.tags, *('protc:implied-' + s for s in ('input', 'output', 'aspect'))):  # FIXME hardcoded fix
            value, children_text = self._fix_implied_input()
            if value:
                return value

        if self.text and not self.text.startswith('https://hyp.is'):
            if 'RRID' not in self.text:
                return self.text

        if self.exact is not None:
            return self.exact
        elif self._type == 'reply':
            return ''
        else:
            raise ValueError(f'{self.shareLink} {self.id} has no text and no exact and is not a reply.')

    @property
    def tags(self):
        skip_tags = []
        add_tags = []
        for reply in self.replies:
            corrections = reply.tag_corrections
            if corrections is not None:
                op = corrections[0].split(':',1)[1]
                if op in ('add', 'replace'):
                    add_tags.extend(corrections[1:])
                if op == 'replace':
                    skip_tags.extend(self._cleaned__tags)  # FIXME recursion error
                elif op == 'delete':
                    skip_tags.extend(corrections[1:])

        out = []
        for tag in self._tags:
            if tag not in skip_tags:
                out.append(tag)
        return out + add_tags

    @property
    def _cleaned_tags(self):
        for tag in self.tags:
            if not any(tag.startswith(prefix) for prefix in self.prefix_skip_tags):
                yield tag

    @property
    def _cleaned__tags(self):
        for tag in self._tags:
            if not any(tag.startswith(prefix) for prefix in self.prefix_skip_tags):
                yield tag

    @property
    def tag_corrections(self):
        tagset = self._tags
        for ctag in self.control_tags:
            if ctag in self._tags:
                if ctag == 'annotation-correction':
                    ctag = 'annotation-tags:replace'
                return [ctag] + list(self._cleaned_tags)

    def text_correction(self, suffix):  # also handles additions
        ctag = 'annotation-text:' + suffix
        if ctag in self.tags:
            return self.text
        #elif suffix == 'children' and self.text.startswith('https://hyp.is'):
            #return self.text

    def children_correction(self, suffix):
        ctag = 'annotation-children:' + suffix
        if ctag in self.tags:
            return self.text

    @property
    def _children_text(self):
        correction = ''
        for reply in self.replies:
            _correction = reply.text_correction('children')
            if _correction is not None:
                correction = _correction
        if correction:
            return correction

        if 'protc:implied-input' in self.tags:  # FIXME hardcoded fix
            value, children_text = self._fix_implied_input()
            if children_text:
                return children_text

        if 'hyp.is' not in self.text:
            children_text = ''
        elif anyMembers(self.tags, *self.children_tags):
            children_text = ''
        elif any(tag.startswith('PROTCUR:') for tag in self.tags) and noneMembers(self.tags, *self.text_tags):
            # accidental inclusion of feedback that doesn't start with SKIP eg https://hyp.is/HLv_5G43EeemJDuFu3a5hA
            children_text = ''
        else:
            children_text = self.text
        return children_text

    @staticmethod
    def _get_children_ids(children_text):
        for line in splitLines(children_text):
            if line:
                id_ = idFromShareLink(line)
                if id_ is not None:
                    yield id_

    @property
    def _children_delete(self):  # FIXME not mutex with annotation-text:children... will always override
        delete = ''
        for reply in self.replies:  # FIXME assumes the ordering of replies is in chronological order... validate?
            _delete = reply.children_correction('delete')
            if _delete is not None:
                delete = _delete
        if delete:
            for id_ in self._get_children_ids(delete):
                yield id_

    @property
    def _children_ids(self):
        skip = set(self._children_delete)
        if skip:
            for id_ in self._get_children_ids(self._children_text):
                if id_ not in skip:
                    yield id_
                #else:
                    #printD('deleted', id_)  # FIXME this seems like it is called too many times...
        else:
            yield from self._get_children_ids(self._children_text)

    @property
    def children(self):  # TODO various protc:implied- situations...
        if 'protc:implied-aspect' in self.tags:
            yield self.parent
            return
        for id_ in self._children_ids:
            child = self.getObjectById(id_)
            for reply in child.replies:
                if 'protc:implied-aspect' in reply.tags:
                    yield reply
                    child = None  # inject the implied aspect between the input and the parameter
                    break

            if child is not None: # sanity
                yield child  # buildAst will have a much eaiser time operating on these single depth childs

    def __eq__(self, other):
        return (self.id == other.id
                and self.text == other.text
                and set(self.tags) == set(other.tags))
    
    def __hash__(self):
        return hash(self.__class__.__name__ + self.id)

    def __repr__(self, depth=0):
        start = '|' if depth else ''
        t = ' ' * 4 * depth + start

        parent_id = f"\n{t}parent_id:    {self.parent.id} {self.__class__.__name__}.byId('{self.parent.id}')" if self.parent else ''
        tag_text = f'\n{t}tags:         {self.tags}' if self.tags else ''
        lct = list(self._cleaned_tags)
        ct = f'\n{t}cleaned tags: {lct}' if self.references and lct and lct != self.tags else ''
        tc = f'\n{t}tag_corrs:    {self.tag_corrections}' if self.tag_corrections else ''

        replies = ''.join(r.__repr__(depth + 1) for r in self.replies)
        rep_ids = f'\n{t}replies:      ' + ' '.join(f"{self.__class__.__name__}.byId('{r.id}')" for r in self.replies)
        replies_text = f'\n{t}replies:{replies}' if self.reprReplies else rep_ids if replies else ''
        childs = ''.join(c.__repr__(depth + 1)
                         if self not in c.children
                         else f'\n{" " * 4 * (depth + 1)}* {c.id} has a circular reference with this node {self.id}'  # avoid recursion
                         for c in self.children
                         if c is not self.parent  # avoid accidental recursion with replies of depth 1 TODO WE NEED TO GO DEEPER
                        )
        childs_text = f'\n{t}children:{childs}' if childs else ''
        return (f'\n{t.replace("|","")}*--------------------'
                f"\n{t}{self.__class__.__name__ + ':':<14}{self.shareLink} {self.__class__.__name__}.byId('{self.id}')"
                f'\n{t}isAstNode:    {self.isAstNode}'
                f'{parent_id}'
                f'\n{t}exact:        {self.exact}'
                f'\n{t}text:         {self.text}'
                f'\n{t}value:        {self.value}'
                f'{tag_text}'
                f'{ct}'
                f'{tc}'
                f'{replies_text}'
                f'{childs_text}'
                f'\n{t}____________________')


class AstGeneric(Hybrid):
    """ Base class that implements the core methods needed for parsing various namespaces """
    #indentDepth = 2
    #objects = {}
    #_order = tuple()
    #_topLevel = tuple()
    @staticmethod
    def _value_escape(value):
        return '"' + value.strip().replace('"', '\\"') + '"'

    def _dispatch(self):
        def inner():
            return self._value_escape(self.value)
        type_ = self.astType
        if type_ is None:
            raise TypeError(f'Cannot dispatch on NoneType!\n{super().__repr__()}')
        namespace, dispatch_on = type_.split(':', 1)
        if namespace != self.__class__.__name__:
            raise TypeError(f'{self.__class__.__name__} does not dispatch on types from '
                            f'another namespace ({namespace}).')
        dispatch_on = dispatch_on.replace('*', '').replace('-', '_')
        return getattr(self, dispatch_on, inner)()

    @classmethod
    def parsed(cls):
        return ''.join(sorted(repr(o) for o in cls.objects.values() if o is not None and o.isAstNode))

    @classmethod
    def topLevel(cls):
        return ''.join(sorted(repr(o) for o in cls.objects.values() if o is not None and o.isAstNode and o.astType in cls._topLevel))

    @property
    def astType(self):
        if self.isAstNode:
            tags = self.tags
            for tag in self._order:
                ctag = 'protc:' + tag
                if ctag in tags:
                    return ctag
            if len(tags) == 1:
                return tags[0]
            elif len(list(self._cleaned_tags)) == 1:
                return next(iter(self._cleaned_tags))
            else:
                tl = ' '.join(f"'{t}" for t in sorted(tags))
                printD(f'Warning: something weird is going on with (annotation-tags {tl}) and self._order {self._order}')

    @property
    def astValue(self):
        if self.isAstNode:
            return self._dispatch()

    def __gt__(self, other):
        #if type(self) == type(other):
        if not self.isAstNode:
            return False
        elif not other.isAstNode:
            return True
        else:
            try:
                #return self.astType + self.astValue >= other.astType + other.astValue
                return self.astType + self.value >= other.astType + other.value
            except TypeError as e:
                embed()
                raise e

    def __lt__(self, other):
        #if type(self) == type(other) and self.isAstNode and other.isAstNode:
        return not self.__gt__(other)
        #else:
            #return False

    def __repr__(self, depth=1, nparens=1, plast=True, top=True, cycle=False):
        out = ''
        type_ = self.astType 
        if type_ is None:
            if cycle:
                print('Circular link in', self.shareLink)
                out = f"'(circular-link no-type {cycle.id})" + ')' * nparens
            else:
                return super().__repr__()
        value = self.astValue
        comment = f'  ; {self.shareLink}'

        children = list(self.children)  # better to run the generator once up here
        if children:
            linestart = '\n' + ' ' * self.indentDepth * depth
            nsibs = len(children)
            cs = []
            for i, c in enumerate(children):
                new_plast = i + 1 == nsibs
                # if we are at the end of multiple children the child node needs to add one more paren
                if new_plast:
                    new_nparens = nparens + 1
                else:
                    new_nparens = 1  # new children start their own tree, nparens only tracks the last node
                try:
                    if self in c.children:  # FIXME cannot detect longer cycles
                        if cycle:
                            print('Circular link in', self.shareLink)
                            s = f"'(circular-link {cycle.id})" + ')' * nparens
                        else:
                            s = c.__repr__(depth + 1, new_nparens, new_plast, False, self)
                    else:
                        s = c.__repr__(depth + 1, new_nparens, new_plast, False)
                except TypeError as e:
                    raise TypeError(f'{c} is not an {self.__class__.__name__}') from e
                cs.append(s)
            childs = comment + linestart + linestart.join(cs)
        else:
            childs = ')' * nparens + comment  

        start = '\n(' if top else '('
        return f'{start}{type_} {value}{childs}'


class protc(AstGeneric):
    indentDepth = 2
    objects = {}  # TODO updates
    _order = (  # ordered based on dependence and then by frequency of occurence for performance (TODO tagdefs stats automatically)
              'structured-data-record',  # needs to come first since record contents also have a type (e.g. protc:parameter*)
              'parameter*',
              'input',
              'invariant',
              'references-for-use',
              'aspect',
              'black-box-component',
              '*measure',  # under represented
              'output',
              'objective*',
              'no-how-error',
              'order',
              'repeat',
              'implied-aspect',
              'how',
              '*make*',  # FIXME output?? also yay higher order functions :/
              'symbolic-measure',
              'implied-input',
              'result',
              'output-spec',
              'structured-data-header',
              'telos',
              'executor-verb',
            )
    _topLevel = tuple('protc:' + t for t in ('input',
                                             'output',
                                             'implied-input',
                                             'implied-output',
                                             '*measure',
                                             'symbolic-measure',
                                             'black-black-component',
                                            ))

    def parameter(self):
        out = getattr(self, '_parameter', None)
        if out is not None:
            return repr(out)
        value = self.value
        if value == '':  # breaks the parser :/
            return ''
        cleaned = value.replace(' mL–1', ' * mL–1').replace(' kg–1', ' * kg–1')  # FIXME temporary (and bad) fix for superscript issues
        cleaned = cleaned.strip()
        cleaned_orig = cleaned

        # ignore gargabe at the start
        success = False
        front = ''
        while not success:
            success_always_true, v, rest = parsing.parameter_expression(cleaned)
            try:
                success = v[0] != 'param:parse-failure'
            except TypeError as e:
                raise e
            if not success:
                if len(cleaned) > 1:
                    more_front, cleaned = cleaned[0], cleaned[1:]
                    front += more_front
                else:
                    front += cleaned
                    success, v, rest = parsing.parameter_expression(cleaned_orig)  # reword but whatever
                    error_output.append((success, v, rest))
                    break

        def format_unit_atom(param_unit, name, prefix=None):
            if prefix is not None:
                return f"({param_unit} '{name} '{prefix})"
            else:
                return f"({param_unit} '{name})"

        def format_value(tuple_):
            out = []
            if tuple_:
                if 0:  # list_[0] == 'param:unit':  # TODO unit atom, unit by itself can be much more complex
                    return format_unit(*tuple_)
                else:
                    for v in tuple_:
                        if type(v) is tuple:
                            v = format_value(v)
                        if v is not None:
                            out.append(f'{v}')
            if out:
                return '(' + ' '.join(out) + ')'

        if v is not None:
            v = format_value(v)
        test_params.append((value, (success, v, rest)))
        self._parameter = ParameterValue(success, v, rest, front)
        return repr(self._parameter)


    def _parameter_parsec(self):  # more than 2x slower than my version >_<
        out = getattr(self, '_parameter', None)
        if out is not None:
            return repr(out)
        value = self.value
        if value == '':  # breaks the parser :/
            return ''
        cleaned = value.replace(' mL–1', ' * mL–1').replace(' kg–1', ' * kg–1')  # FIXME temporary (and bad) fix for superscript issues
        cleaned = cleaned.strip()
        cleaned_orig = cleaned

        # ignore gargabe at the start
        success = False
        front = ''
        max_ = len(cleaned)
        v = None
        for i in range(max_):
            Value = parsing_parsec.parameter_expression(cleaned, i)
            if Value.status:
                v = Value.value
                front = cleaned[:i]
                rest = cleaned[Value.index:]
                break

        if v is None:
            rest = cleaned
            front = ''

        def format_unit_atom(param_unit, name, prefix=None):
            if prefix is not None:
                return f"({param_unit} '{name} '{prefix})"
            else:
                return f"({param_unit} '{name})"

        def format_value(tuple_):
            out = []
            if tuple_:
                if 0:  # list_[0] == 'param:unit':  # TODO unit atom, unit by itself can be much more complex
                    return format_unit(*list_)
                else:
                    for v in tuple_:
                        if type(v) is tuple:
                            v = format_value(v)
                        if v is not None:
                            out.append(f'{v}')
            if out:
                return '(' + ' '.join(out) + ')'

        if v is not None:
            v = format_value(v)
        test_params.append((value, (Value.status, v, rest)))
        self._parameter = ParameterValue(success, v, rest, front)
        return repr(self._parameter)

    def invariant(self):
        return self.parameter()
    def input(self):
        value = self.value
        #data = sgv.findByTerm(value)  # TODO could try the annotate endpoint? FIXME _extremely_ slow so skipping
        data = None
        if data:
            subset = [d for d in data if value in d['labels']]
            if subset:
                data = subset[0]
            else:
                data = data[0]  # TODO could check other rules I have used in the past
            id_ = data['curie'] if 'curie' in data else data['iri']
            value += f" ({id_}, {data['labels'][0]})"
        else:
            test_input.append(value)
        return self._value_escape(value)

    def output(self):
        return self.input()
    #def implied_input(self): return value
    #def structured_data(self): return self.value
    #def measure(self): return self.value
    #def symbolic_measure(self): return self.value
#
# utility

class ParameterValue:
    def __init__(self, success, v, rest, front):
        self.value = success, v, rest, front
    def __repr__(self):
        success, v, rest, front = self.value
        if not success:
            out = str((success, v, rest))
        else:
            out = v + (f' (rest-front "{rest}" "{front}")' if rest or front else '')
        return out

test_params = []
test_input = []

def main():
    from pprint import pformat
    from protcur import get_annos, get_annos_from_api, start_loop
    from time import sleep
    import requests

    mem_file = '/tmp/protocol-annotations.pickle'

    global annos  # this is too useful not to do
    annos = get_annos(mem_file)  # TODO memoize annos... and maybe start with a big offset?
    stream_loop = start_loop(annos, mem_file)
    #hybrids = [Hybrid(a, annos) for a in annos]
    #printD('protcs')
    #@profile_me
    def rep():
        repr(hybrids)
    #rep()

    @profile_me
    def perftest():
        protcs = [protc(a, annos) for a in annos]
        return protcs
    protcs = perftest()
    @profile_me
    def text():
        t = protc.parsed()
        with open('/tmp/protcur.rkt', 'wt') as f: f.write(t)
        # don't return to avoid accidentally repring these fellows :/
    #p = protc.byId('nofnAgwtEeeIoHcLZfi9DQ')  # serialization error due to a cycle
    #print(repr(p))
    text()
    tl = protc.topLevel()
    with open('/tmp/top-protcur.rkt', 'wt') as f: f.write(tl)
    embed()

def _more_main():
    input_text_args = [(basic_start(a).strip(),) for a in annos if 'protc:input' in a.tags or 'protc:output' in a.tags]
    async_getter(sgv.findByTerm, input_text_args)  # prime the cache FIXME issues with conflicting loops...

    stream_loop.start()

    i = papers(annos)

    t = citation_tree(annos)
    PREFIXES = {'protc':'http://protc.olympiangods.org/curation/tags/',
                'hl':'http://hypothesis-local.olympiangods.org/'}
    PREFIXES.update(makePrefixes('rdfs'))
    g = makeGraph('', prefixes=PREFIXES)
    for p, s, o in t:
        su = hypothesis_local(s)
        ou = hypothesis_local(o)
        g.add_node(su, p, ou)
        g.add_node(su, 'rdfs:label', s)  # redundant
        g.add_node(ou, 'rdfs:label', o)  # redundant
    ref_graph = g.make_scigraph_json(RFU, direct=True)
    tree, extra = creatTree('hl:ma2015.pdf', RFU, 'OUTGOING', 10, json=ref_graph)

    irs = sorted(inputRefs(annos))

    trees = makeAst()
    writeTrees(trees)

    test_inputs = sorted(set(test_input))
    def check_inputs():
        with open(os.path.expanduser('~/files/bioportal_api_keys'), 'rt') as f:
            bioportal_api_key = f.read().strip()
        def getBiop(term):
            #url = f'http://data.bioontology.org/search?q={term}&ontologies=CHEBI&apikey={bioportal_api_key}'
            url = f'http://data.bioontology.org/search?q={term}&apikey={bioportal_api_key}'
            print(url)
            return requests.get(url)

        res = [(t, getBiop(t)) for t in test_inputs]
        jsons = [(t, r.json()) for t, r in res if r.ok] 

        def chebis(j):
            return set((c['@id'], c['prefLabel'] if 'prefLabel' in c else tuple(c['synonym']))
                       for c in j['collection'] if 'CHEBI' in c['@id'])
        cs = [(t, chebis(j)) for t, j in jsons]
        cs = set((t, r) for t, a in cs for r in a if a)
        cs = sorted(((t, (c.rsplit('/',1)[-1].replace('_',':'), m)) for t, (c, m) in cs), key=lambda v:v[0])
        ids_only = sorted(set(list(zip(*cs))[1]), key=lambda v:v[0])
        check = [(i, sgv.findById(i)) for i in sorted(set(i for i, n in ids_only))]
        in_ = [c for c, v in check if v]
        in_val = [(c, v) for c, v in check if v]
        missing = [c for c, v in check if v is None]
        ids_only = [(i, n) for i, n in ids_only if i not in in_]
        cs_out = [(t, (c, n)) for t, (c, n) in cs if c not in in_]
        return res, jsons, cs_out, ids_only, missing

    #res, jsons, cs_out, ids_only, missing = check_inputs()
    #with open(os.path.expanduser('~/ni/nifstd/chebimissing2.txt'), 'wt') as f: f.write(pformat(cs_out))
    #with open(os.path.expanduser('~/ni/nifstd/chebimissing_id_names2.txt'), 'wt') as f: f.write(pformat(ids_only))
    #with open(os.path.expanduser('~/ni/nifstd/chebimissing_ids2.txt'), 'wt') as f: f.write('\n'.join(missing))

    embed()
    # HOW DO I KILL THE STREAM LOOP!??!

if __name__ == '__main__':
    main()
