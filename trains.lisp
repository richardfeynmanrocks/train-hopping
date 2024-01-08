(ql:quickload :plump)
(ql:quickload :clss)
(ql:quickload :dexador)
(ql:quickload :cl-ppcre)
(ql:quickload :alexandria)

;; Utilities.

(defmacro dovector ((elt vec) &body body)
  "Just coerces it to a list." 
  `(dolist (,elt (coerce ,vec 'list))
	 ,@body))

(defclass naive-time ()
  ((hour :initarg :hour
		 :type fixnum)
   (min :initarg :min
		:type fixnum)))

(defmethod time-after ((time naive-time) other-time)
  (cond ((> (slot-value time 'hour) (slot-value other-time 'hour)) t)
		((and (= (slot-value time 'hour) (slot-value other-time 'hour))
			  (>= (slot-value time 'min) (slot-value other-time 'min))) t)
		(t nil)))

(defmethod time-equal ((time naive-time) other-time)
  (and (= (slot-value time 'hour) (slot-value other-time 'hour))
	   (= (slot-value time 'min) (slot-value other-time 'min))))

(defun parse-time-string (str)
  (cl-ppcre:register-groups-bind (hh mm half) ("(\\d\\d?):(\\d\\d)([ap]m)" str)
    (make-instance 'naive-time
				   :hour (+ (parse-integer hh) (if (string= half "pm") 12 0))
				   :min (parse-integer mm))))

;; Train stuff.

(defun get-schedule ()
  (plump:parse
   (dex:get "https://www.caltrain.com/?active_tab=route_explorer_tab")))

(defun filter-elements (elems)
  (remove-if (lambda (e)
			   (or (eq 'PLUMP-DOM:TEXT-NODE (type-of e))
				   (search "zone-change" (plump:attribute e "class"))				  
				   (search "display: none" (plump:attribute e "style"))))
			 elems))

(deftype service-type ()
  '(member :local :weekend :limited3 :limited4 :limited5 :bullet))  

(defun make-service-type (str)
  (cond ((string= str "L1") :local)
		((string= str "L2") :weekend)
		((string= str "L3") :limited3)
		((string= str "L4") :limited4)
		((string= str "L5") :limited5)
		((string= str "B7") :bullet)))	 

(defclass station ()
  ((name :initarg :name
		 :type string)
   (zone :initarg :zone
		 :type fixnum)))

(defun make-station (name zone)
  (make-instance 'station :name name :zone zone))

(defun station-equal (station1 station2)
  (and (string= (slot-value station1 'name)
				(slot-value station2 'name))
	   (= (slot-value station1 'zone)
		  (slot-value station2 'zone))))				

(defclass stop ()
  ((station :initarg :station
			:type station)
   (time :initarg :time
		 :type naive-time)))

(defun stop-equal (stop1 stop2)
  (and (station-equal (slot-value stop1 'station)
					  (slot-value stop2 'station))
	   (naive-time-equal (slot-value stop1 'time)
						 (slot-value stop2 'time))))

(defclass train ()
  ((number
	:initarg :number
	:accessor train-number
	:type fixnum)
   (direction
	:initarg :direction
	:accessor train-direction
	:type symbol)
   (service
	:initarg :service-type
	:accessor train-service
	:type service-type)	
   (stops
	:initform '()
	:accessor train-stops
	:type cons)))

(defun get-trains ()
  (let ((tables (clss:select "tbody" (get-schedule)))
		(directions #(northbound southbound)))
	(alexandria:flatten
	 (mapcar
	  (lambda (i)
		;; NOTE: Really weird hack. Plump parses as if there are more children than there actually are??? Skipping works fine though.
		(let* ((rows (filter-elements (plump:children (aref tables i))))
			   (numbers (map 'vector (lambda (col) (parse-integer (plump:text col)))
							 (subseq (plump:children (aref rows 0)) 2)))
			   (types (map 'vector (lambda (col) (make-service-type (plump:text col)))
						   (subseq (plump:children (aref rows 1)) 2)))
			   (trains (map 'vector (lambda (num type)
									  (make-instance 'train :number num :service-type type
															:direction (aref directions i)))
							numbers types)))
		  (dovector (row (subseq rows 2))
			(let ((station (make-instance 'station :zone (parse-integer (plump:text (aref (plump:children row) 0)))
												   :name (plump:text (aref (plump:children row) 1)))))
			  (dotimes (i (length trains))
				(if (not (string= (plump:text (aref (plump:children row) (+ i 2))) "--"))
					(setf (train-stops (aref trains i))
						  (append (train-stops (aref trains i))
								  (list (make-instance 'stop :station station
															 :time (parse-time-string (plump:text (aref (plump:children row) (+ i 2))))))))))))
		  (coerce trains 'list))) '(0 1)))))

(defun get-weekday-trains ()
  (remove-if
   (lambda (tr)
	 (eq (train-service tr)
		 :weekend))
   (get-trains)))
  

(defun upcoming-trains (trains station-name time)
  (sort (remove-if
		 (lambda (x) (= (length x) 1))
		 (mapcar (lambda (tr)
				   (cons tr (remove-if (lambda (s)
										 (not (and (string= station-name (slot-value (slot-value s 'station) 'name))
												   (time-after (slot-value s 'time) time))))
									   (train-stops tr))))
				 trains))
		(lambda (x y) (not (time-after (slot-value (nth 1 x) 'time) (slot-value (nth 1 y) 'time))))))
  

(dolist (s (upcoming-stops (get-weekday-trains) "Gilroy" (parse-time-string "2:00am")))
  (print (format nil "Train ~D (~A, ~A) arrives at ~A at ~D:~2,'0D"
				 (train-number (nth 0 s))
				 (train-direction (nth 0 s))
				 (train-service (nth 0 s))
				 (slot-value (slot-value (nth 1 s) 'station) 'name)
				 (slot-value (slot-value (nth 1 s) 'time) 'hour)
				 (slot-value (slot-value (nth 1 s) 'time) 'min)))
