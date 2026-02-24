/****************************************************************************
** Generated QML type registration code
**
** WARNING! All changes made in this file will be lost!
*****************************************************************************/

#include <QtQml/qqml.h>
#include <QtQml/qqmlmoduleregistration.h>

#if __has_include(</home/fares/dev/github/dropmeteamwork/GUI/src/gui/server.py>)
#  include </home/fares/dev/github/dropmeteamwork/GUI/src/gui/server.py>
#endif


#if !defined(QT_STATIC)
#define Q_QMLTYPE_EXPORT Q_DECL_EXPORT
#else
#define Q_QMLTYPE_EXPORT
#endif
Q_QMLTYPE_EXPORT void qml_register_types_DropMe()
{
    QT_WARNING_PUSH QT_WARNING_DISABLE_DEPRECATED
    qmlRegisterTypesAndRevisions<Server>("DropMe", 1);
    QT_WARNING_POP
    qmlRegisterModule("DropMe", 1, 0);
}

static const QQmlModuleRegistration dropMeRegistration("DropMe", qml_register_types_DropMe);
