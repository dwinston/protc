#lang racket/base

(require
 "direct-model.rkt"
 (for-syntax
  racket/base
  racket/syntax
  syntax/parse
  "utils.rkt"
  "identifier-functions.rkt"
  (except-in "direct-model.rkt" #%top)
  "syntax-classes.rkt"))

(provide (all-defined-out)
         (rename-out [input implied-input])
         (all-from-out "direct-model.rkt"))

;;;

; aspect and input are the only 2 that need to lift units out

(define-syntax (actualize stx)
  (syntax-parse stx
    [thing #;(_ wut:id (~optional (~seq #:prov prov)) rest:expr ...)
     #''thing]))

(define-syntax (input stx)
  (syntax-parse stx
    #:datum-literals (hyp:)
    #;
    (aspect protc:aspct
            input protc:input
            parameter* protc:parameter*
            invariant protc:invariant)
    [(_ name:str (hyp: (quote id))
        (~alt ;inv/par:sc-cur-inv/par
         inv:sc-cur-invariant
         par:sc-cur-parameter*
         body:expr) ...)
     #:with black-box (datum->syntax #'name (string->symbol (syntax-e #'name)))
     #'(actualize black-box #:prov (hyp: 'id)
                  (~? inv.lifted) ...
                  (~? par.lifted) ...
                  (~? body (raise-syntax-error "HOW?!")) ...
               )
     ]))

(define-syntax (output stx)
  (syntax-parse stx
    #:datum-literals (hyp: quote spec make)
    #:literal-sets (protc-fields protc-ops)  ; whis this not working?
    [(_ name:str (hyp: (quote id)) (~alt asp:sc-cur-aspect
                                         par:sc-cur-parameter*
                                         inv:sc-cur-invariant
                                         bbc:sc-cur-bbc
                                         input:expr) ...)
     #:with spec-name (if (number? (syntax-e #'id))
                          (fmtid "_~a" #'id)  ; recall that #'_id doesn't work because the type is not strictly known
                          #'id)
     #:with black-box (datum->syntax #'name (string->symbol (syntax-e #'name)))
     #'(define-make (spec-name black-box)
         "this is a docstring from curation!"
         #:prov (hyp: 'id)
         ;#:vars (what is the issue here folks)
         ; othis stuff works at top level ...
         ;#:inputs (input ...)
         ;#:constraints ((~? asp) ... (~? par) ...)
         #:inputs (input ...)
         #:constraints ((~? asp) ... (~? par.lifted) ... (~? inv.lifted) ...)
         )
     ]))
(module+ test
  (output "thing" (hyp: 'prov-a)
          (parameter* (quantity 100 (unit 'meters 'milli)) (hyp: 'prov-b)))
  )

(define (black-box-component name prov . aspects) #f)

(define-syntax (aspect stx)
  (syntax-parse stx
    #:datum-literals (hyp: quote)
    [(_ name:str
        (hyp: (quote id))
        (~optional
         (~or* par:sc-cur-parameter*
               inv:sc-cur-invariant)))
     ; TODO check that the given unit matches
     #`(quote #,stx)]))
(module+ test
  (aspect "mass" (hyp: '0))
  (aspect "bob"
          (hyp: '1)
          (parameter*
           (quantity
            10
            (unit 'kelvin 'milli))
           (hyp: '2))))

(define-syntax (unit stx)
  (syntax-parse stx
    [(_ unit-base:sc-unit-name (~optional unit-prefix:sc-prefix-name))
     #`(quote #,stx)  ; TODO
     ]))

(define-syntax (unit-expr stx)
  (syntax-parse stx
    [(_ unit-expr:sc-unit-expr)
     #`(quote #,stx)  ; TODO
     ]))

(define (invariant aspect value prov) #f)

(define-syntax (parameter* stx)
  (syntax-parse stx
    [_:sc-cur-parameter*
     #`(quote #,stx)]))

(module+ test
  (parameter* (quantity 100 (unit 'meters 'milli)) (hyp: 'prov-0))
  (output "thing" (hyp: 'prov-1)
          (parameter* (quantity 100 (unit 'meters 'milli)) (hyp: 'prov-2)))
  #; ; I think these are failing because I need a syntax level thunk not a normal thunk
  (check-exn exn:fail:syntax? (thunk (parameter* 100 (unit 'meters 'milli) (hyp: 'prov-1)))))

(define (objective* text prov) #f)
(define (telos text prov) #f)
(define (result aspect value prov) #f)

(define (order) #f)
(define (repeate) #f)

(define (references-for-use) #f)
(define (references-for-evidence) #f)

(define (black-box) #f)

;;; TODO

(define-syntax (*measure stx)
  #''TODO)

(define-syntax (symbolic-measure stx)
  #''TODO)

(define-syntax (version stx)
  #''TODO)

(define-syntax (i-have-no-idea stx)
  #''TODO)

(define-syntax (para:dilution stx)
  #''TODO)

(module+ test

  (define-syntax (test?-2 stx)
    (syntax-parse stx
      [(_ name:id one:expr two:expr)
       #'(define-syntax (name stx)
           (syntax-parse stx
             [(_
               (~optional (~seq #:1 one))
               (~optional (~seq #:2 two))
               )
              #'(~? one two)]
             )
           )

       ]))

  (test?-2 all-opt
           one
           two)

  (all-opt #:1 1 #:2 2)
  )

#;; also dones't work :/
(module+ test
  ; all the other variants just don't work :/ ~optional and ~seq complain
  ; maybe there is a way to use with-syntax?
  (with-syntax ([opt (datum->syntax #f '~optional)]
                [seq (datum->syntax #f '~seq)]
                )
    (test?-2 all-opt-??
             (#'opt (#'seq #:1 one))
             (#'opt (#'seq #:2 two))))

  (all-opt-?? 1 2))

#;; this fails because ~? cannot take 3 arguments
(module+ test
  (define-syntax (test?-3 stx)
    (syntax-parse stx
      [(_ name:id one:expr two:expr three:expr)
       #'(define-syntax (name stx)
           (syntax-parse stx
             [(_
               one two three
               )
              #'(~? one two three)]))]))
  (test?-3 all-opt
           (~optional (~seq #:1 one))
           (~optional (~seq #:2 two))
           (~optional (~seq #:3 three)))

  (all-opt #:1 '1)
  (all-opt #:2 '2)
  (all-opt #:3 '3)

  )


(module+ test
  (require rackunit
           "utils.rkt"
           "syntax-classes.rkt"
           syntax/parse
           racket/function)
  (define-syntax (test stx)
    (syntax-parse stx
      [(_ thing:sc-cur-invariant)
       #''thing.lifted]))

  #;
  (define-syntax (thunk stx)
    #`(λ () #,(cdr (syntax->list stx))))

  #; ; i have no idea why this doesn't work
  (check-exn exn:fail:syntax? (thunk (test (parameter* (hyp: '0) (quantity 10 (unit 'meters))))))

  (test (invariant (quantity 10 (unit meters)) (hyp: '0)))

  (input "thing" (hyp: '1) (parameter* (quantity 10 (unit meters)) (hyp: '2)))

  (define-syntax (unit-> stx)
    (syntax-parse stx
      [(_ name:expr prefix:expr)
       #:with n (fmtid "~a" (datum->syntax #'name (syntax-local-eval #'name)))
       #:with p (fmtid "~a" (datum->syntax #'prefix (syntax-local-eval #'prefix)))
       #'(unit n p)]
      ))

  (define (runtime-unit name prefix)
    (with-syntax ([n name]
                  [p prefix])
      (syntax-parse #'(unit n p)
        [thing:sc-unit
         (syntax->datum #'thing)])))

  (unit meters milli)
  (unit 'meters 'milli)  ; not entirely sure if we want this ... but ok
  (unit-> 'meters 'milli)
  #; ; another cases where I think I need to trap the error as I do in rrid-metadata
  ; however, the fact that syntax-local-eval fails to find thunk and (unit a b) needs
  ; identifiers means that the runtime-unit implementation is vastly preferable
  (check-exn exn:fail:syntax:unbound? (thunk (unit-> ((thunk 'meters)) ((thunk 'milli)))))
  (runtime-unit ((thunk 'meters)) ((thunk 'milli)))
  (check-exn exn:fail:syntax? (thunk (runtime-unit 'nota 'unit)))
  (let ([m 'meters]
        [_m 'milli])
    (runtime-unit m _m)))