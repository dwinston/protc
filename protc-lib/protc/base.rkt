#lang racket/base

;A pure racket implementation of protc with no major modifications to the reader.

; see https://docs.racket-lang.org/guide/language-collection.html

(require protc/private/kernel
         protc/private/base
         )
(provide (all-from-out protc/private/kernel)
         (all-from-out protc/private/base)
         )

(module reader syntax/module-reader protc/base
        ;#:read read
        ;#:read-syntax read-syntax
        ;#:whole-body-readers? #t
        #:info protc/base-get-info
        #:module-wrapper protc-module-wrapper
        (require protc/private/reader
                 (only-in protc/get-info protc/base-get-info)
                 (submod protc/private/kernel module-wrapper)))
